"""
MCP 工具桥接：发现 → ToolDef，调用 → call_tool（参考 claude-code mcp-tools.ts）

- 命名 `mcp__{server}__{tool}`，非法字符归一化 `[^a-zA-Z0-9_-]` → `_`
- inputSchema 直接透传；description 截 2048；readOnlyHint → is_concurrency_safe
- 调用：isError=True → 错误文本回传（不抛异常，交由模型自纠）
- 结果：text 优先，structuredContent JSON 化，100k 字符截断
"""

import json
import re
from typing import Dict, List, Optional

from mcp import ClientSession

import logging

from ..core.types import ToolDef
from .client import MCPManager
from .config import MCPServerConfig

logger = logging.getLogger("app.llm.mcp")

TOOL_NAME_PREFIX = "mcp__"
MAX_DESCRIPTION_CHARS = 2048
MAX_TOOL_RESULT_CHARS = 100_000

_INVALID_CHARS = re.compile(r"[^a-zA-Z0-9_-]")


def mcp_tool_name(server: str, tool: str) -> str:
    return f"{TOOL_NAME_PREFIX}{_INVALID_CHARS.sub('_', server)}__{_INVALID_CHARS.sub('_', tool)}"


def _format_content(result, *, task_id: str = "") -> str:
    """call_tool 结果 → 文本：text 优先，structuredContent JSON 化；超限统一走 result_budget 落盘预览"""
    from ..tools.result_budget import apply_result_budget

    parts: List[str] = []
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    structured = getattr(result, "structured_content", None) or getattr(result, "structuredContent", None)
    if not parts and structured:
        parts.append(json.dumps(structured, ensure_ascii=False))
    if not parts:
        return "(空结果)"
    return apply_result_budget("mcp_result", "\n".join(parts), task_id=task_id, max_chars=MAX_TOOL_RESULT_CHARS)


def make_mcp_tool_def(cfg: MCPServerConfig, manager: MCPManager, tool) -> ToolDef:
    """把 server 端单个 tool 包装为本地 ToolDef（handler 绑定该 server）"""
    display_name = mcp_tool_name(cfg.name, tool.name)
    desc = (tool.description or f"MCP tool '{tool.name}' from server '{cfg.name}'")[:MAX_DESCRIPTION_CHARS]

    async def _call(*call_args, **call_kwargs) -> str:
        # registry 以位置参数传 input dict；直接调用时可能用关键字
        payload = call_args[0] if call_args and isinstance(call_args[0], dict) else call_kwargs
        session: ClientSession = await manager.get_session(cfg)
        result = await session.call_tool(tool.name, arguments=payload or {})
        if result.isError:
            return f"MCP 工具执行错误: {_format_content(result)}"
        return _format_content(result)

    annotations = getattr(tool, "annotations", None)  # annotations 可能为 None
    read_only = bool(annotations and getattr(annotations, "readOnlyHint", False))

    return ToolDef(
        name=display_name,
        description=desc,
        # mcp SDK 新版 Tool 字段为 input_schema（旧版 inputSchema），双兼容避免属性错误
        params_schema=(
            getattr(tool, "input_schema", None)
            or getattr(tool, "inputSchema", None)
            or {"type": "object", "properties": {}}
        ),
        handler=_call,
        is_concurrency_safe=read_only,
    )


async def discover_mcp_tools(
    manager: Optional[MCPManager] = None,
    servers: Optional[Dict[str, MCPServerConfig]] = None,
    config_path: Optional[str] = None,  # 保留参数兼容旧签名；实际配置源为 config/mcp.json
) -> List[ToolDef]:
    """连接全部配置的 server 并发现工具，返回 ToolDef 列表"""
    mgr = manager or MCPManager()
    if servers is None:
        from .service import enabled_server_configs

        servers = enabled_server_configs()
    cfgs = servers
    defs: List[ToolDef] = []
    for name, cfg in cfgs.items():
        try:
            session = await mgr.connect(cfg)
            listed = await session.list_tools()
        except Exception as e:
            logger.warning(f"⚠️ [mcp] server '{name}' 连接/发现失败: {e}")
            continue
        for tool in listed.tools:
            try:
                defs.append(make_mcp_tool_def(cfg, mgr, tool))
            except Exception as e:  # noqa: BLE001 - 单工具包装失败跳过，不炸整个发现流程
                logger.warning(f"⚠️ [mcp] server '{name}' 工具 '{tool.name}' 包装失败: {e}")
        logger.info(f"[mcp] server '{name}' 发现 {len(listed.tools)} 个工具")
    return defs
