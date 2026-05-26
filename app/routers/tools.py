"""
工具清单接口
- 返回统一工具注册表中的可用工具（含类型分类和可用性状态）
- MCP Provider 工具管理：列出、启用/禁用、可用性摘要
"""

import logging
import os
from typing import Any, Dict, List, Optional, Set
from pathlib import Path

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel

from app.core.config import settings
from app.core.env import get_env
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


class ToggleToolPayload(BaseModel):
    enabled: bool


def _check_tushare_available() -> bool:
    """检查 Tushare 受限工具当前是否可用。"""
    if not getattr(settings, "TUSHARE_ENABLED", False):
        return False

    token = (getattr(settings, "TUSHARE_TOKEN", "") or get_env("TUSHARE_TOKEN", "")).strip()
    return bool(token)


def _get_disabled_tools() -> Set[str]:
    """获取已禁用的工具列表"""
    try:
        if _DISABLED_TOOLS_FILE.exists():
            import json
            data = json.loads(_DISABLED_TOOLS_FILE.read_text(encoding='utf-8'))
            return set(data.get('disabled', []))
    except Exception as e:
        logger.error(f"读取禁用工具列表失败: {e}")
    return set()


def _save_disabled_tools(disabled: Set[str]):
    """保存已禁用的工具列表（原子写入）"""
    try:
        _DISABLED_TOOLS_FILE.parent.mkdir(parents=True, exist_ok=True)
        import json
        import tempfile
        data = json.dumps({'disabled': sorted(list(disabled))}, ensure_ascii=False, indent=2)
        fd, tmp_path = tempfile.mkstemp(suffix=".tmp", dir=str(_DISABLED_TOOLS_FILE.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(data)
            os.replace(tmp_path, str(_DISABLED_TOOLS_FILE))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception as e:
        logger.error(f"保存禁用工具列表失败: {e}")
        raise


# ── MCP Provider 工具名称集合 ──
_MCP_PROVIDER_NAMES: Set[str] = set()


def _is_mcp_provider_tool(name: str) -> bool:
    """判断工具名是否属于 MCP Provider（项目内置金融数据工具）。"""
    return name in _MCP_PROVIDER_NAMES


def _classify_tool(name: str, registry: ToolRegistry) -> str:
    """根据工具名和注册表信息判断工具类型（三类：builtin / mcp / skill）。"""
    if name in registry.get_builtin_tool_metas():
        return TOOL_TYPE_BUILTIN
    # MCP Provider 工具也归为 builtin
    if _is_mcp_provider_tool(name):
        return TOOL_TYPE_BUILTIN
    # Skill 工具名通常是 load_skill
    if name == "load_skill":
        return TOOL_TYPE_SKILL
    return TOOL_TYPE_MCP


async def _get_builtin_availability(registry: ToolRegistry) -> Dict[str, bool]:
    """获取内置工具的可用性状态（基于 MongoDB 数据检测）。"""
    try:
        from app.engine.tools.builtin.domain_checker import AvailabilityCache
        cache = AvailabilityCache.get_instance()
        return dict(cache.all_results)
    except Exception:
        return {}


def _get_tool_display_name(name: str, registry: ToolRegistry) -> str:
    """获取工具的中文显示名。"""
    metas = registry.get_builtin_tool_metas()
    if name in metas:
        return metas[name].get("display_name", name)
    # MCP Provider 工具
    for t in _MCP_TOOLS:
        if t["name"] == name:
            return t["description"].split("（")[0].split("(")[0]
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
    - tool_type: builtin | mcp_provider | mcp_external | skill
    - display_name: 中文显示名
    - source: 来源标识（向后兼容）
    - availability: { status, detail } (当 with_availability=True)
    """
    global _MCP_PROVIDER_NAMES
    _MCP_PROVIDER_NAMES = {t["name"] for t in _MCP_TOOLS}

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
            except Exception:
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

    # 添加 MCP Provider 工具（它们可能不在 LangChain 工具列表中）
    for mcp_tool in _MCP_TOOLS:
        name = mcp_tool["name"]
        if name not in seen:
            seen.add(name)
            availability = {"status": "unknown", "detail": ""}
            if with_availability:
                availability = {"status": "available", "detail": ""}
            items.append({
                "name": name,
                "description": mcp_tool.get("description", ""),
                "tool_type": TOOL_TYPE_BUILTIN,  # MCP Provider 工具归为内置
                "display_name": mcp_tool.get("description", name).split("（")[0].split("(")[0],
                "source": mcp_tool.get("source", "builtin-proxy"),
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
        # 先检查 LangGraph 内置工具
        is_available = builtin_availability.get(name, None)
        if is_available is not None:
            return {
                "status": "available" if is_available else "no_data",
                "detail": "" if is_available else "MongoDB 中暂无数据，请先同步",
            }
        # 再检查 MCP Provider 工具（均通过 DataInterface，始终可用）
        for t in _MCP_TOOLS:
            if t["name"] == name:
                return {"status": "available", "detail": ""}
        return {"status": "unknown", "detail": ""}

    if tool_type == TOOL_TYPE_MCP:
        return {"status": "unknown", "detail": "依赖外部 MCP 连接器状态"}

    if tool_type == TOOL_TYPE_SKILL:
        return {"status": "available", "detail": ""}

    return {"status": "unknown", "detail": ""}


# ============== MCP Provider 工具管理端点 ==============

# MCP Provider 工具定义
# - source="builtin-proxy": 有对应内置工具实现，此处仅作前端展示代理
# - source="local-mcp": MCP Provider server.py 中实际注册的工具
# 所有工具均通过 DataInterface 获取数据，不依赖特定数据源
_MCP_TOOLS = [
    # ── MCP Provider 实际注册的工具 ──
    {"name": "get_stock_data", "description": "获取股票行情数据及技术指标", "category": "核心数据", "source": "local-mcp"},
    {"name": "get_stock_fundamentals", "description": "获取股票基本面数据", "category": "核心数据", "source": "local-mcp"},
    {"name": "get_finance_news", "description": "获取财经新闻搜索", "category": "新闻时间", "source": "local-mcp"},
    # ── 内置工具透传声明（前端展示用）──
    {"name": "get_stock_news", "description": "获取股票相关新闻", "category": "核心数据", "source": "builtin-proxy"},
    {"name": "get_stock_sentiment", "description": "获取市场情绪分析", "category": "核心数据", "source": "builtin-proxy"},
    {"name": "get_china_market_overview", "description": "获取A股市场整体概况", "category": "核心数据", "source": "builtin-proxy"},
    {"name": "get_stock_data_minutes", "description": "获取分钟级K线数据", "category": "分钟数据", "source": "builtin-proxy"},
    {"name": "get_company_performance_unified", "description": "获取公司业绩数据（A股/港股/美股）", "category": "业绩数据", "source": "builtin-proxy"},
    {"name": "get_money_flow", "description": "获取资金流向数据", "category": "宏观资金", "source": "builtin-proxy"},
    {"name": "get_margin_trade", "description": "获取融资融券数据", "category": "宏观资金", "source": "builtin-proxy"},
    {"name": "get_index_data", "description": "获取指数行情数据", "category": "指数其他", "source": "builtin-proxy"},
    {"name": "get_block_trade", "description": "获取大宗交易数据", "category": "指数其他", "source": "builtin-proxy"},
    {"name": "get_dragon_tiger_inst", "description": "获取龙虎榜数据", "category": "指数其他", "source": "builtin-proxy"},
    {"name": "get_current_timestamp", "description": "获取当前时间戳", "category": "新闻时间", "source": "builtin-proxy"},
]


@router.get("/mcp")
async def list_mcp_tools(
    user: dict = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    列出所有 MCP Provider 工具（含可用性状态）

    MCP Provider 工具是项目内置的金融数据工具，通过 MCP 协议暴露给外部 LLM。
    """
    try:
        disabled_tools = _get_disabled_tools()

        # 构建工具列表
        tools = []
        for tool in _MCP_TOOLS:
            tools.append({
                "name": tool["name"],
                "description": tool["description"],
                "source": tool.get("source", "builtin-proxy"),
                "tool_type": TOOL_TYPE_BUILTIN,  # MCP Provider 工具归为内置
                "category": tool["category"],
                "available": True,  # 所有工具均通过 DataInterface，始终可用
                "enabled": tool["name"] not in disabled_tools,
            })

        # 计算摘要
        enabled_count = sum(1 for t in tools if t["enabled"])

        return {
            "success": True,
            "data": tools,
            "count": len(tools),
            "summary": {
                "total": len(tools),
                "available": len(tools),
                "unavailable": 0,
                "enabled": enabled_count,
                "disabled": len(tools) - enabled_count,
            }
        }

    except Exception as e:
        logger.error(f"获取 MCP 工具列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取 MCP 工具列表失败: {str(e)}")


@router.patch("/mcp/{name}/toggle")
async def toggle_mcp_tool(
    name: str,
    payload: ToggleToolPayload,
    user: dict = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    启用/禁用 MCP Provider 工具
    """
    try:
        # 验证工具是否存在
        tool_names = {t["name"] for t in _MCP_TOOLS}
        if name not in tool_names:
            raise HTTPException(status_code=404, detail=f"工具不存在: {name}")

        # 更新禁用列表
        disabled_tools = _get_disabled_tools()

        if payload.enabled:
            disabled_tools.discard(name)
        else:
            disabled_tools.add(name)

        _save_disabled_tools(disabled_tools)

        return {
            "success": True,
            "data": {
                "name": name,
                "enabled": payload.enabled,
                "message": f"工具已{'启用' if payload.enabled else '禁用'}"
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"切换工具状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"切换工具状态失败: {str(e)}")


@router.get("/mcp/availability-summary")
async def get_mcp_availability_summary(
    user: dict = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    获取 MCP Provider 工具可用性摘要
    """
    try:
        disabled_tools = _get_disabled_tools()

        # 按分类统计
        by_category: Dict[str, Dict[str, int]] = {}
        for tool in _MCP_TOOLS:
            cat = tool["category"]
            if cat not in by_category:
                by_category[cat] = {"total": 0, "available": 0, "enabled": 0}

            by_category[cat]["total"] += 1
            by_category[cat]["available"] += 1  # 均通过 DataInterface，始终可用

            if tool["name"] not in disabled_tools:
                by_category[cat]["enabled"] += 1

        # 计算总体统计
        total = len(_MCP_TOOLS)

        return {
            "success": True,
            "data": {
                "total": total,
                "available": total,
                "unavailable": 0,
                "enabled": total - len(disabled_tools),
                "disabled": len(disabled_tools),
                "by_category": by_category,
                "disabled_tools": sorted(list(disabled_tools)),
            }
        }

    except Exception as e:
        logger.error(f"获取可用性摘要失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取可用性摘要失败: {str(e)}")
