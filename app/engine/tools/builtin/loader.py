"""
内置工具加载器

从 builtin/tools/ 各领域模块加载所有内置工具。
"""
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

# 领域模块列表
_DOMAIN_MODULES = [
    "market",
    "news",
    "fundamentals",
    "sentiment",
    "china_market",
    "capital_flow",
    "macro",
    "fund",
    "others",
]


def _import_domain_module(module_name: str):
    """动态导入领域模块"""
    try:
        import importlib
        module_path = f"app.engine.tools.builtin.tools.{module_name}"
        return importlib.import_module(module_path)
    except ImportError:
        logger.error(f"❌ 无法加载领域模块: {module_name}")
        return None
    except Exception as e:
        logger.error(f"❌ 加载领域模块 {module_name} 失败: {e}")
        return None


def load_builtin_tools(toolkit_config: Optional[Dict] = None) -> List:
    """
    加载所有内置工具

    遍历 builtin/tools/ 下的 9 个领域模块，
    收集 TOOL_FUNCTIONS 并包装为 LangChain Tool。

    Args:
        toolkit_config: 工具配置字典（当前未使用，保留接口）

    Returns:
        LangChain Tool 列表
    """
    import importlib

    from langchain_core.tools import tool as lc_tool
    from app.engine.tools.builtin.availability import (
        get_availability_summary,
        check_all_tools_availability,
    )

    all_tools = []
    all_tool_metas = {}  # {tool_name: {"data_source_map": [...], "analyst_map": [...]}}

    for module_name in _DOMAIN_MODULES:
        module = _import_domain_module(module_name)
        if module is None:
            continue

        tool_functions = getattr(module, "TOOL_FUNCTIONS", [])
        data_source_map = getattr(module, "DATA_SOURCE_MAP", {})
        analyst_map = getattr(module, "ANALYST_MAP", {})

        if not tool_functions:
            logger.warning(f"⚠️ 模块 {module_name} 没有暴露 TOOL_FUNCTIONS")
            continue

        for func in tool_functions:
            try:
                # 使用 langchain_core.tools.tool 装饰器包装
                langchain_tool = lc_tool(func)

                # 附加元数据到工具
                tool_name = getattr(langchain_tool, "name", func.__name__)

                all_tool_metas[tool_name] = {
                    "data_source_map": data_source_map.get(tool_name, []),
                    "analyst_map": analyst_map.get(tool_name, []),
                    "module": module_name,
                }

                # 标记为内置工具（LangChain Tool 的 metadata 可能是不可变 pydantic 字段）
                existing_meta = getattr(langchain_tool, "metadata", None) or {}
                new_meta = {
                    **existing_meta,
                    "tool_category": "builtin",
                    "builtin_module": module_name,
                }
                try:
                    langchain_tool.metadata = new_meta
                except Exception:
                    # pydantic v2 的 Tool 某些版本不允许直接赋值，忽略即可
                    pass

                all_tools.append(langchain_tool)

            except Exception as e:
                logger.error(f"❌ 包装工具 {func.__name__} 失败: {e}")

    # 打印可用性摘要
    if all_tool_metas:
        # 收集所有 data_source_map
        combined_data_source_map = {}
        for tool_name, meta in all_tool_metas.items():
            if meta["data_source_map"]:
                combined_data_source_map[tool_name] = meta["data_source_map"]

        if combined_data_source_map:
            summary = get_availability_summary(combined_data_source_map)
            logger.info(f"📊 内置工具可用性摘要:")
            logger.info(f"   总工具数: {summary['total']}")
            logger.info(f"   可用: {summary['available']}")
            logger.info(f"   不可用: {summary['unavailable']}")
            logger.info(f"   可用数据源: {summary['available_sources']}")
            if summary['unavailable'] > 0:
                unavailable_names = [
                    name for name, detail in summary['details'].items()
                    if not detail['available']
                ]
                logger.warning(f"   不可用工具: {', '.join(unavailable_names)}")

    logger.info(f"✅ 内置工具加载完成: {len(all_tools)} 个")
    return all_tools


def get_builtin_tool_metas() -> Dict[str, Dict]:
    """
    获取所有内置工具的元数据

    Returns:
        {tool_name: {"data_source_map": [...], "analyst_map": [...], "module": "..."}}
    """
    metas = {}

    for module_name in _DOMAIN_MODULES:
        module = _import_domain_module(module_name)
        if module is None:
            continue

        data_source_map = getattr(module, "DATA_SOURCE_MAP", {})
        analyst_map = getattr(module, "ANALYST_MAP", {})

        tool_functions = getattr(module, "TOOL_FUNCTIONS", [])
        for func in tool_functions:
            metas[func.__name__] = {
                "data_source_map": data_source_map.get(func.__name__, []),
                "analyst_map": analyst_map.get(func.__name__, []),
                "module": module_name,
            }

    return metas
