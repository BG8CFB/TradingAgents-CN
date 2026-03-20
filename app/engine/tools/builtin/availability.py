"""
内置工具可用性检测

基于数据源状态动态检测工具是否可用。
工具可用 ⟺ 其 DATA_SOURCE_MAP 中至少一个数据源可用。
"""
import logging
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


def get_available_data_sources() -> Set[str]:
    """
    获取当前可用的数据源名称集合

    Returns:
        可用数据源名称的集合，如 {"tushare", "akshare"}
    """
    try:
        from app.data.manager import DataSourceManager

        manager = DataSourceManager()
        available_adapters = manager.get_available_adapters()

        sources = set()
        for adapter in available_adapters:
            name = adapter.name.lower()
            # 标准化数据源名称
            if 'tushare' in name:
                sources.add('tushare')
            elif 'akshare' in name or 'ak' in name:
                sources.add('akshare')
            elif 'baostock' in name or 'bst' in name:
                sources.add('baostock')
            elif 'finnhub' in name:
                sources.add('finnhub')
            else:
                # 使用原始名称（小写）
                sources.add(name.lower())

        return sources
    except Exception as e:
        logger.warning(f"获取可用数据源失败: {e}")
        return set()


def check_tool_availability(
    tool_name: str,
    data_source_map: Dict[str, List[str]]
) -> bool:
    """
    检查单个工具是否可用

    Args:
        tool_name: 工具名称
        data_source_map: 工具到数据源的映射 {tool_name: ["tushare", "akshare"]}

    Returns:
        True 如果至少一个依赖的数据源可用
    """
    required_sources = data_source_map.get(tool_name, [])
    if not required_sources:
        # 没有数据源要求的工具，默认可用
        return True

    available = get_available_data_sources()

    for source in required_sources:
        if source.lower() in available:
            return True

    return False


def check_all_tools_availability(
    data_source_map: Dict[str, List[str]]
) -> Dict[str, bool]:
    """
    批量检查所有工具的可用性

    Args:
        data_source_map: {tool_name: [required_source, ...]}

    Returns:
        {tool_name: is_available}
    """
    available = get_available_data_sources()

    result = {}
    for tool_name, required_sources in data_source_map.items():
        if not required_sources:
            result[tool_name] = True
            continue

        is_available = any(
            source.lower() in available
            for source in required_sources
        )
        result[tool_name] = is_available

    return result


def get_availability_summary(
    data_source_map: Dict[str, List[str]]
) -> dict:
    """
    获取工具可用性摘要信息

    Returns:
        {
            "total": 总工具数,
            "available": 可用工具数,
            "unavailable": 不可用工具数,
            "available_sources": ["tushare", "akshare"],
            "details": {tool_name: {"available": bool, "required_sources": [...]}}
        }
    """
    available_sources = get_available_data_sources()
    availability = check_all_tools_availability(data_source_map)

    available_count = sum(1 for v in availability.values() if v)
    unavailable_count = sum(1 for v in availability.values() if not v)

    details = {}
    for tool_name, is_available in availability.items():
        details[tool_name] = {
            "available": is_available,
            "required_sources": data_source_map.get(tool_name, []),
        }

    return {
        "total": len(availability),
        "available": available_count,
        "unavailable": unavailable_count,
        "available_sources": sorted(available_sources),
        "details": details,
    }
