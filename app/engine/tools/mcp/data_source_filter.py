"""
数据源过滤器 - 根据数据源可用性自动过滤工具

当用户未配置Tushare或Tushare不可用时，自动过滤掉仅支持Tushare的工具
"""
import logging
from typing import List, Callable, Set

logger = logging.getLogger(__name__)


# 仅支持Tushare的工具列表（不支持AkShare）
TUSHARE_ONLY_TOOLS: Set[str] = {
    'get_csi_index_constituents',     # 中证指数成分股
    'get_macro_econ',                  # 宏观经济数据
    'get_money_flow',                  # 资金流向数据
    'get_margin_trade',                # 融资融券（AkShare不提供个股明细）
    'get_fund_manager_by_name',        # 基金经理信息
    'get_finance_news',                # 财经新闻搜索
    'get_hot_news_7x24',               # 7x24快讯
    # 🔥 注意：get_company_performance_unified 不在此列表中
    #    因为A股和港股部分数据类型支持AkShare回退
    'get_stock_sentiment',             # 社交媒体情绪（Reddit/Twitter）
}


def check_tushare_available() -> bool:
    """
    检查Tushare是否可用

    通过DataSourceManager检查Tushare适配器的is_available()状态
    is_available()会实际测试接口调用（stock_basic），不仅仅是检查token

    Returns:
        True: Tushare可用（已配置且接口测试通过）
        False: Tushare不可用（未配置或接口测试失败）
    """
    try:
        from app.data.manager import DataSourceManager

        # 获取所有可用的数据源
        manager = DataSourceManager()
        available_adapters = manager.get_available_adapters()

        # 检查Tushare是否在可用列表中
        for adapter in available_adapters:
            if 'tushare' in adapter.name.lower():
                logger.info(f"✅ Tushare数据源可用: {adapter.name}")
                return True

        logger.info("⚠️ Tushare数据源不可用（未配置或接口测试失败）")
        return False

    except Exception as e:
        logger.error(f"❌ 检查Tushare可用性时出错: {e}")
        # 出错时保守处理，认为Tushare不可用
        return False


def should_include_tool(tool_func: Callable, tushare_available: bool = None) -> bool:
    """
    判断是否应该包含该工具

    Args:
        tool_func: 工具函数
        tushare_available: Tushare是否可用（None时自动检查）

    Returns:
        True: 包含该工具
        False: 过滤掉该工具
    """
    func_name = tool_func.__name__

    # 如果是仅Tushare的工具
    if func_name in TUSHARE_ONLY_TOOLS:
        # 自动检查Tushare是否可用
        if tushare_available is None:
            tushare_available = check_tushare_available()

        if not tushare_available:
            logger.warning(f"🚫 工具 '{func_name}' 被过滤（需要Tushare但数据源不可用）")
            return False
        else:
            logger.info(f"✅ 工具 '{func_name}' 保留（Tushare可用）")
            return True

    # 其他工具（支持AkShare或双数据源）都保留
    return True


def get_filtered_tool_list(
    tool_funcs: List[Callable],
    tushare_available: bool = None
) -> List[Callable]:
    """
    获取过滤后的工具列表

    Args:
        tool_funcs: 原始工具函数列表
        tushare_available: Tushare是否可用（None时自动检查）

    Returns:
        过滤后的工具函数列表
    """
    filtered_tools = []
    filtered_count = 0
    filtered_names = []

    # 自动检查Tushare是否可用
    if tushare_available is None:
        tushare_available = check_tushare_available()

    for func in tool_funcs:
        if should_include_tool(func, tushare_available):
            filtered_tools.append(func)
        else:
            filtered_count += 1
            filtered_names.append(func.__name__)

    if filtered_count > 0:
        logger.warning(f"📊 共过滤 {filtered_count} 个工具: {', '.join(filtered_names)}")
        logger.info(f"📊 保留工具数: {len(filtered_tools)}/{len(tool_funcs)}")
    else:
        logger.info(f"✅ 所有 {len(tool_funcs)} 个工具均可用（Tushare状态: {'可用' if tushare_available else '不可用'}）")

    return filtered_tools


def get_tool_filter_summary(tool_funcs: List[Callable]) -> dict:
    """
    获取工具过滤摘要信息

    Args:
        tool_funcs: 工具函数列表

    Returns:
        摘要字典，包含：
        - total: 总工具数
        - tushare_only: 仅Tushare工具数
        - dual_source: 双数据源工具数
        - filtered: 被过滤的工具数（如果Tushare不可用）
        - tushare_available: Tushare是否可用
    """
    tushare_available = check_tushare_available()

    tushare_only_count = 0
    dual_source_count = 0

    for func in tool_funcs:
        func_name = func.__name__
        if func_name in TUSHARE_ONLY_TOOLS:
            tushare_only_count += 1
        else:
            dual_source_count += 1

    filtered_count = tushare_only_count if not tushare_available else 0
    available_count = len(tool_funcs) - filtered_count

    return {
        'total': len(tool_funcs),
        'tushare_only': tushare_only_count,
        'dual_source': dual_source_count,
        'filtered': filtered_count,
        'available': available_count,
        'tushare_available': tushare_available,
        'tushare_status': '可用' if tushare_available else '不可用'
    }


if __name__ == "__main__":
    """测试过滤器"""
    print("="*80)
    print("🧪 测试数据源过滤器")
    print("="*80)

    # 检查Tushare状态
    available = check_tushare_available()
    print(f"\nTushare状态: {'✅ 可用' if available else '❌ 不可用'}")

    # 显示工具分类
    print(f"\n📊 工具分类:")
    print(f"   仅Tushare工具: {len(TUSHARE_ONLY_TOOLS)}个")
    print(f"   工具列表: {', '.join(sorted(TUSHARE_ONLY_TOOLS))}")

    print("\n" + "="*80)
