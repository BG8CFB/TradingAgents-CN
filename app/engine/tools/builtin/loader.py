"""
内置工具加载器

从 BUILTIN_TOOL_REGISTRY 加载所有内置工具，包装为 LangChain StructuredTool。
"""
import logging
from typing import Dict, List, Optional

from app.engine.tools.builtin.registry import (
    BUILTIN_TOOL_REGISTRY,
    BuiltinToolSpec,
    get_spec_by_id,
    get_specs_by_ids,
)

logger = logging.getLogger(__name__)


def load_builtin_tools(toolkit_config: Optional[Dict] = None) -> List:
    """
    加载所有内置工具

    从 BUILTIN_TOOL_REGISTRY 遍历，包装为 LangChain StructuredTool。
    可用性过滤在 simple_agent_factory 中完成（基于 AvailabilityCache）。

    Args:
        toolkit_config: 工具配置字典（当前未使用，保留接口）

    Returns:
        LangChain Tool 列表
    """
    import inspect
    from langchain_core.tools import StructuredTool

    all_tools = []

    for spec in BUILTIN_TOOL_REGISTRY:
        try:
            # 先触发延迟导入，获取真正的函数对象
            fn = spec.fn

            # 如果 fn 是 lazy wrapper，先调用一次获取真实函数
            real_fn = fn
            if fn.__doc__ in ("", None):
                # 尝试直接导入真实模块
                import importlib
                _M = "app.engine.tools.builtin.tools"
                module_map = {
                    "daily_quotes": ("market", "get_stock_data"),
                    "intraday_quotes": ("market", "get_stock_data_minutes"),
                    "market_quotes": ("market", "get_index_data"),
                    "financial_data": ("fundamentals", "get_company_performance_unified"),
                    "fundamentals": ("fundamentals", "get_stock_fundamentals"),
                    "news": ("news", "get_stock_news"),
                    "sentiment": ("sentiment", "get_stock_sentiment"),
                    "china_market": ("china_market", "get_china_market_overview"),
                    "dragon_tiger": ("china_market", "get_dragon_tiger_inst"),
                    "block_trade": ("china_market", "get_block_trade"),
                    "money_flow": ("capital_flow", "get_money_flow"),
                    "margin_trade": ("capital_flow", "get_margin_trade"),
                }

                mapping = module_map.get(spec.tool_id)
                if mapping:
                    mod = importlib.import_module(f"{_M}.{mapping[0]}")
                    real_fn = getattr(mod, mapping[1])

            # 用 StructuredTool 显式包装，不依赖函数 docstring
            sig = inspect.signature(real_fn)

            tool = StructuredTool.from_function(
                func=real_fn,
                name=spec.tool_id,
                description=spec.description,
            )

            # 附加元数据
            try:
                existing_meta = getattr(tool, "metadata", None) or {}
                tool.metadata = {
                    **existing_meta,
                    "tool_category": "builtin",
                    "tool_id": spec.tool_id,
                    "builtin_domains": spec.domains,
                }
            except Exception as e:
                logger.debug(f"设置内置工具元数据失败 ({spec.tool_id}): {e}")
                pass

        except Exception as e:
            logger.error(f"❌ 包装工具 {spec.tool_id} 失败: {e}")

    logger.info(f"✅ 内置工具加载完成: {len(all_tools)} 个")
    return all_tools


def get_builtin_tool_specs() -> List[BuiltinToolSpec]:
    """获取所有内置工具的规格"""
    return list(BUILTIN_TOOL_REGISTRY)
