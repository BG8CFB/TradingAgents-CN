"""
工具清单接口
- 返回统一工具注册表中的可用工具名称（含本地项目工具，可选启用 MCP）
- 本地 MCP 工具管理：列出、启用/禁用、可用性摘要
"""

import logging
from typing import Any, Dict, List, Set
from pathlib import Path

from fastapi import APIRouter, Depends, Query, HTTPException, Body
from pydantic import BaseModel

from app.routers.auth_db import get_current_user
from app.engine.agents import Toolkit
from app.engine.tools.registry import get_all_tools
from app.engine.tools.mcp import LANGCHAIN_MCP_AVAILABLE, get_mcp_loader_factory

router = APIRouter(prefix="/api/tools", tags=["tools"])
logger = logging.getLogger(__name__)

# 禁用工具存储文件
_DISABLED_TOOLS_FILE = Path("config/disabled_tools.json")


class ToggleToolPayload(BaseModel):
    enabled: bool


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
    """保存已禁用的工具列表"""
    try:
        _DISABLED_TOOLS_FILE.parent.mkdir(parents=True, exist_ok=True)
        import json
        _DISABLED_TOOLS_FILE.write_text(
            json.dumps({'disabled': sorted(list(disabled))}, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )
    except Exception as e:
        logger.error(f"保存禁用工具列表失败: {e}")
        raise


def _tool_info(tool: Any, source: str = "project", external_metadata: Dict[str, Any] = None) -> Dict[str, Any]:
    name = getattr(tool, "name", None)
    description = getattr(tool, "description", None) or getattr(tool, "__doc__", "") or ""
    
    # 尝试从 metadata 获取 source (MCP 工具通常存储在这里)
    metadata = getattr(tool, "metadata", {}) or {}
    if not isinstance(metadata, dict):
        metadata = {}
    
    # 合并外部元数据 (例如来自 wrapper)
    if external_metadata:
        metadata.update(external_metadata)

    metadata_server = metadata.get("server_name")
    
    tool_source = (
        getattr(tool, "server_name", None) or 
        getattr(tool, "server", None) or 
        metadata_server or
        source
    )
    
    return {
        "name": name,
        "description": description.strip() if isinstance(description, str) else "",
        "source": tool_source,
    }


@router.get("/available")
async def list_available_tools(
    include_mcp: bool = Query(True, description="是否包含 MCP 工具"),
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    返回统一工具清单（默认包含项目内工具，按需包含 MCP 工具）。
    include_mcp=True 时总是尝试加载 MCP，未配置则自动忽略。
    """
    toolkit = Toolkit()
    
    # 获取 MCP 工具加载器
    mcp_tool_loader = None
    if include_mcp and LANGCHAIN_MCP_AVAILABLE:
        try:
            factory = get_mcp_loader_factory()
            # MCP 连接在应用启动时已建立，直接使用
            # 创建工具加载器（仅外部 MCP 工具，避免与本地重复）
            mcp_tool_loader = factory.create_loader([], include_local=False)
        except Exception as e:
            logger.warning(f"获取 MCP 工具加载器失败: {e}")
    
    tools = get_all_tools(
        toolkit=toolkit,
        enable_mcp=include_mcp,
        mcp_tool_loader=mcp_tool_loader,
    )

    # 去重并序列化
    seen = set()
    items: List[Dict[str, Any]] = []
    for tool in tools:
        # 尝试从 wrapper 获取 metadata (针对 RunnableBinding)
        external_metadata = {}
        
        # 1. 检查 config 中的 metadata (RunnableBinding 常用)
        if hasattr(tool, "config") and isinstance(tool.config, dict):
            if "metadata" in tool.config:
                external_metadata.update(tool.config["metadata"])
        
        # 2. 检查直接的 metadata 属性
        if hasattr(tool, "metadata") and isinstance(tool.metadata, dict):
             external_metadata.update(tool.metadata)

        # 特殊处理 RunnableBinding (MCP 工具可能被 wrap)
        if hasattr(tool, "bound") and not getattr(tool, "name", None):
            try:
                # 尝试从 bound 对象获取 name
                tool = tool.bound
            except Exception:
                pass

        name = getattr(tool, "name", None)
        
        if not name or name in seen:
            continue
        seen.add(name)
        items.append(_tool_info(tool, external_metadata=external_metadata))
    
    # 如果启用了 MCP，还需要添加外部 MCP 服务器的工具（非 local 的）
    if include_mcp and LANGCHAIN_MCP_AVAILABLE:
        try:
            factory = get_mcp_loader_factory()
            mcp_tools_info = factory.list_available_tools()
            for tool_info in mcp_tools_info:
                tool_name = tool_info.get("name")
                server_name = tool_info.get("serverName", "mcp")
                # 只添加外部 MCP 工具（非 local）
                if tool_name and tool_name not in seen and server_name != "local":
                    seen.add(tool_name)
                    items.append({
                        "name": tool_name,
                        "description": tool_info.get("description", ""),
                        "source": server_name,
                    })
                    logger.info(f"添加外部 MCP 工具: {tool_name} (来源: {server_name})")
        except Exception as e:
            logger.warning(f"获取外部 MCP 工具列表失败: {e}")

    return {"success": True, "data": items, "count": len(items)}


# ============== MCP 本地工具管理端点 ==============

# 20个本地 MCP 工具定义（与 finance.py 对应）
_MCP_TOOLS = [
    {"name": "get_stock_data", "description": "获取股票行情数据及技术指标", "category": "核心数据", "tushare_only": False},
    {"name": "get_stock_news", "description": "获取股票相关新闻", "category": "核心数据", "tushare_only": False},
    {"name": "get_stock_fundamentals", "description": "获取股票基本面数据", "category": "核心数据", "tushare_only": False},
    {"name": "get_stock_sentiment", "description": "获取市场情绪分析", "category": "核心数据", "tushare_only": True},
    {"name": "get_china_market_overview", "description": "获取A股市场整体概况", "category": "核心数据", "tushare_only": False},
    {"name": "get_stock_data_minutes", "description": "获取分钟级K线数据", "category": "分钟数据", "tushare_only": False},
    {"name": "get_company_performance_unified", "description": "获取公司业绩数据（A股/港股/美股）", "category": "业绩数据", "tushare_only": False},
    {"name": "get_macro_econ", "description": "获取宏观经济指标", "category": "宏观资金", "tushare_only": True},
    {"name": "get_money_flow", "description": "获取资金流向数据", "category": "宏观资金", "tushare_only": True},
    {"name": "get_margin_trade", "description": "获取融资融券数据", "category": "宏观资金", "tushare_only": True},
    {"name": "get_fund_data", "description": "获取公募基金数据", "category": "基金数据", "tushare_only": False},
    {"name": "get_fund_manager_by_name", "description": "获取基金经理信息", "category": "基金数据", "tushare_only": True},
    {"name": "get_index_data", "description": "获取指数行情数据", "category": "指数其他", "tushare_only": False},
    {"name": "get_csi_index_constituents", "description": "获取中证指数成份股", "category": "指数其他", "tushare_only": True},
    {"name": "get_convertible_bond", "description": "获取可转债数据", "category": "指数其他", "tushare_only": False},
    {"name": "get_block_trade", "description": "获取大宗交易数据", "category": "指数其他", "tushare_only": False},
    {"name": "get_dragon_tiger_inst", "description": "获取龙虎榜数据", "category": "指数其他", "tushare_only": False},
    {"name": "get_finance_news", "description": "获取财经新闻搜索", "category": "新闻时间", "tushare_only": True},
    {"name": "get_hot_news_7x24", "description": "获取7x24快讯", "category": "新闻时间", "tushare_only": True},
    {"name": "get_current_timestamp", "description": "获取当前时间戳", "category": "新闻时间", "tushare_only": False},
]


@router.get("/mcp")
async def list_mcp_tools(
    user: dict = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    列出所有本地 MCP 工具（含可用性状态）
    """
    try:
        # 检查数据源可用性
        from app.engine.tools.mcp.data_source_filter import check_tushare_available

        tushare_available = check_tushare_available()
        disabled_tools = _get_disabled_tools()

        # 构建工具列表
        tools = []
        for tool in _MCP_TOOLS:
            is_available = True
            if tool["tushare_only"] and not tushare_available:
                is_available = False

            tools.append({
                "name": tool["name"],
                "description": tool["description"],
                "source": "local-mcp",
                "category": tool["category"],
                "available": is_available,
                "tushare_only": tool["tushare_only"],
                "enabled": tool["name"] not in disabled_tools,
            })

        # 计算摘要
        enabled_count = sum(1 for t in tools if t["enabled"])
        available_count = sum(1 for t in tools if t["available"])
        tushare_only_count = sum(1 for t in tools if t["tushare_only"])

        return {
            "success": True,
            "data": tools,
            "count": len(tools),
            "summary": {
                "total": len(tools),
                "available": available_count,
                "unavailable": len(tools) - available_count,
                "enabled": enabled_count,
                "disabled": len(tools) - enabled_count,
                "tushare_only": tushare_only_count,
                "tushare_available": tushare_available,
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
    启用/禁用 MCP 工具
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
    获取 MCP 工具可用性摘要
    """
    try:
        from app.engine.tools.mcp.data_source_filter import check_tushare_available

        tushare_available = check_tushare_available()
        disabled_tools = _get_disabled_tools()

        # 按分类统计
        by_category = {}
        for tool in _MCP_TOOLS:
            cat = tool["category"]
            if cat not in by_category:
                by_category[cat] = {"total": 0, "available": 0, "enabled": 0}

            by_category[cat]["total"] += 1

            is_available = True
            if tool["tushare_only"] and not tushare_available:
                is_available = False

            if is_available:
                by_category[cat]["available"] += 1

            if tool["name"] not in disabled_tools:
                by_category[cat]["enabled"] += 1

        # 计算总体统计
        total = len(_MCP_TOOLS)
        tushare_only_tools = [t for t in _MCP_TOOLS if t["tushare_only"]]
        available = total - (len(tushare_only_tools) if not tushare_available else 0)

        return {
            "success": True,
            "data": {
                "total": total,
                "available": available,
                "unavailable": total - available,
                "enabled": total - len(disabled_tools),
                "disabled": len(disabled_tools),
                "tushare_available": tushare_available,
                "by_category": by_category,
                "disabled_tools": sorted(list(disabled_tools)),
            }
        }

    except Exception as e:
        logger.error(f"获取可用性摘要失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取可用性摘要失败: {str(e)}")

