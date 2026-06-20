"""
基础数据同步子包：封装与股票基础信息同步相关的阻塞调用与处理函数。
- utils.py：与 Tushare 的阻塞式获取函数（股票列表、最新交易日、日度基础数据）
- processing.py：共享的文档构建/指标处理函数
"""
from .processing import add_financial_metrics
from .utils import (
    fetch_daily_basic_mv_map,
    fetch_latest_roe_map,
    find_latest_trade_date,
    fetch_stock_basic_df,
)

__all__ = [
    "add_financial_metrics",
    "fetch_daily_basic_mv_map",
    "fetch_latest_roe_map",
    "fetch_stock_basic_df",
    "find_latest_trade_date",
]

