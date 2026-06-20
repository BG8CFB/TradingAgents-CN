"""
工具清单接口
- 返回统一工具注册表中的可用工具（含类型分类和可用性状态）
"""

import logging
from typing import Any, Dict, List, Set
from pathlib import Path

from fastapi import APIRouter, Depends, Query

from app.core.config import settings
from app.utils.ds_key_utils import get_datasource_api_key
from app.routers.auth_db import get_current_user
from app.engine.agents import Toolkit
from app.engine.tools.registry import (
    ToolRegistry,
    TOOL_TYPE_BUILTIN,
    TOOL_TYPE_MCP,
    TOOL_TYPE_SKILL,
)
from app.engine.tools.mcp import LANGCHAIN_MCP_AVAILABLE, get_mcp_loader_factory

router = APIRouter(prefix="/api/tools", tags=["Tools"])
logger = logging.getLogger(__name__)

# 禁用工具存储文件
_DISABLED_TOOLS_FILE = Path("config/disabled_tools.json")


def _check_tushare_available() -> bool:
    """检查 Tushare 受限工具当前是否可用。"""
    if not getattr(settings, "TUSHARE_ENABLED", False):
        return False

    token = (get_datasource_api_key("tushare") or "").strip()
    return bool(token)


def _get_disabled_tools() -> Set[str]:
    """获取已禁用的工具列表（保留供未来 toggle 端点复用）"""
    try:
        if _DISABLED_TOOLS_FILE.exists():
            import json
            data = json.loads(_DISABLED_TOOLS_FILE.read_text(encoding='utf-8'))
            return set(data.get('disabled', []))
    except Exception as e:
        logger.error(f"读取禁用工具列表失败: {e}")
    return set()


def _classify_tool(name: str, registry: ToolRegistry) -> str:
    """根据工具名和注册表信息判断工具类型（三类：builtin / mcp / skill）。"""
    if name in registry.get_builtin_tool_metas():
        return TOOL_TYPE_BUILTIN
    if name == "load_skill":
        return TOOL_TYPE_SKILL
    return TOOL_TYPE_MCP


async def _get_builtin_availability(registry: ToolRegistry) -> Dict[str, bool]:
    """获取内置工具的可用性状态（基于 MongoDB 数据检测）。"""
    try:
        from app.engine.tools.builtin.domain_checker import AvailabilityCache
        cache = AvailabilityCache.get_instance()
        return dict(cache.all_results)
    except Exception as e:
        logger.debug(f"获取内置工具可用性状态失败: {e}")
        return {}


def _get_tool_display_name(name: str, registry: ToolRegistry) -> str:
    """获取工具的中文显示名。"""
    metas = registry.get_builtin_tool_metas()
    if name in metas:
        return metas[name].get("display_name", name)
    return name


@router.get("/available")
async def list_available_tools(
    include_mcp: bool = Query(True, description="是否包含 MCP 工具"),
    with_availability: bool = Query(True, description="是否包含可用性状态"),
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    返回统一工具清单，含类型分类和可用性状态。

    每个工具包含：
    - name: 工具标识
    - description: 工具描述
    - tool_type: builtin | mcp | skill
    - display_name: 中文显示名
    - source: 来源标识（向后兼容）
    - availability: { status, detail } (当 with_availability=True)
    """
    toolkit = Toolkit()
    tool_registry = ToolRegistry.get_instance()

    # 获取 MCP 工具加载器
    mcp_tool_loader = None
    if include_mcp and LANGCHAIN_MCP_AVAILABLE:
        try:
            factory = get_mcp_loader_factory()
            mcp_tool_loader = factory.create_loader([], include_local=False)
        except Exception as e:
            logger.warning(f"获取 MCP 工具加载器失败: {e}")

    from app.engine.tools.registry import get_all_tools
    tools = get_all_tools(
        toolkit=toolkit,
        enable_mcp=include_mcp,
        mcp_tool_loader=mcp_tool_loader,
    )

    # 获取可用性数据（仅在内置工具时有效）
    builtin_availability = {}
    if with_availability:
        builtin_availability = await _get_builtin_availability(tool_registry)

    tushare_available = _check_tushare_available()

    # 去重并序列化
    seen: Set[str] = set()
    items: List[Dict[str, Any]] = []

    for tool in tools:
        # 尝试从 wrapper 获取 metadata (针对 RunnableBinding)
        external_metadata: Dict[str, Any] = {}

        if hasattr(tool, "config") and isinstance(tool.config, dict):
            if "metadata" in tool.config:
                external_metadata.update(tool.config["metadata"])

        if hasattr(tool, "metadata") and isinstance(tool.metadata, dict):
            external_metadata.update(tool.metadata)

        # 特殊处理 RunnableBinding (MCP 工具可能被 wrap)
        if hasattr(tool, "bound") and not getattr(tool, "name", None):
            try:
                tool = tool.bound
            except Exception as e:
                logger.debug(f"解包工具绑定失败: {e}")
                pass

        name = getattr(tool, "name", None)
        if not name or name in seen:
            continue
        seen.add(name)

        # 判定工具类型
        tool_type = _classify_tool(name, tool_registry)

        # 获取 source（向后兼容）
        metadata = getattr(tool, "metadata", {}) or {}
        if not isinstance(metadata, dict):
            metadata = {}
        if external_metadata:
            metadata.update(external_metadata)

        tool_source = (
            getattr(tool, "server_name", None)
            or getattr(tool, "server", None)
            or metadata.get("server_name")
            or "project"
        )

        # 获取描述
        description = getattr(tool, "description", None) or getattr(tool, "__doc__", "") or ""
        if isinstance(description, str):
            description = description.strip()

        # 构建可用性信息
        availability = {"status": "unknown", "detail": ""}
        if with_availability:
            availability = _build_availability(
                name, tool_type, builtin_availability, tushare_available
            )

        items.append({
            "name": name,
            "description": description,
            "tool_type": tool_type,
            "display_name": _get_tool_display_name(name, tool_registry),
            "source": tool_source,
            "availability": availability,
        })

    # 添加外部 MCP 服务器的工具（非 local 的）
    if include_mcp and LANGCHAIN_MCP_AVAILABLE:
        try:
            factory = get_mcp_loader_factory()
            mcp_tools_info = factory.list_available_tools()
            for ti in mcp_tools_info:
                tool_name = ti.get("name")
                server_name = ti.get("serverName", "mcp")
                if tool_name and tool_name not in seen and server_name != "local":
                    seen.add(tool_name)
                    items.append({
                        "name": tool_name,
                        "description": ti.get("description", ""),
                        "tool_type": TOOL_TYPE_MCP,
                        "display_name": tool_name,
                        "source": server_name,
                        "availability": {"status": "unknown", "detail": ""},
                    })
        except Exception as e:
            logger.warning(f"获取外部 MCP 工具列表失败: {e}")

    return {"success": True, "data": items, "count": len(items)}


def _build_availability(
    name: str,
    tool_type: str,
    builtin_availability: Dict[str, bool],
    tushare_available: bool,  # noqa: ARG001 — 保留参数签名兼容
) -> Dict[str, str]:
    """构建工具可用性信息。"""
    if tool_type == TOOL_TYPE_BUILTIN:
        is_available = builtin_availability.get(name, None)
        if is_available is not None:
            return {
                "status": "available" if is_available else "no_data",
                "detail": "" if is_available else "MongoDB 中暂无数据，请先同步",
            }
        return {"status": "unknown", "detail": ""}

    if tool_type == TOOL_TYPE_MCP:
        return {"status": "unknown", "detail": "依赖外部 MCP 连接器状态"}

    if tool_type == TOOL_TYPE_SKILL:
        return {"status": "available", "detail": ""}

    return {"status": "unknown", "detail": ""}
