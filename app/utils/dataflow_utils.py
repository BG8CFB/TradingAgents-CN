"""
数据流通用工具函数

从 tradingagents/dataflows/utils.py 迁移而来
"""
from datetime import datetime, timedelta
from app.utils.time_utils import now_utc

from app.utils.logging_manager import get_logger
logger = get_logger('agents')


def get_trading_date_range(target_date=None, lookback_days=10):
    """
    获取用于查询交易数据的日期范围

    策略：获取最近N天的数据，以确保能获取到最后一个交易日的数据
    这样可以自动处理周末、节假日和数据延迟的情况

    Args:
        target_date: 目标日期（datetime对象或字符串YYYY-MM-DD），默认为今天
        lookback_days: 向前查找的天数，默认10天（可以覆盖周末+小长假）

    Returns:
        tuple: (start_date, end_date) 两个字符串，格式YYYY-MM-DD

    Example:
        >>> get_trading_date_range("2025-10-13", 10)
        ("2025-10-03", "2025-10-13")

        >>> get_trading_date_range("2025-10-12", 10)  # 周日
        ("2025-10-02", "2025-10-12")
    """
    # 处理输入日期
    if target_date is None:
        target_date = now_utc()
    elif isinstance(target_date, str):
        target_date = datetime.strptime(target_date, "%Y-%m-%d")

    # 如果是未来日期，使用今天
    today = now_utc()
    if target_date.date() > today.date():
        target_date = today

    # 计算开始日期（向前推N天）
    start_date = target_date - timedelta(days=lookback_days)

    # 返回日期范围
    return start_date.strftime("%Y-%m-%d"), target_date.strftime("%Y-%m-%d")
