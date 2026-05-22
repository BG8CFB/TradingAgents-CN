"""
yfinance HK 港股每日指标 API — 暂不支持独立指标接口。
"""
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


async def fetch_daily_indicators(symbol: str) -> Optional[pd.DataFrame]:
    """获取港股每日指标。

    yfinance 不提供独立的每日指标（PE/PB/市值等）批量接口，
    部分指标可从 Ticker.info 中获取但非时间序列。
    当前返回 None。如需指标数据请使用 Tushare HK 或 AKShare HK。

    Parameters
    ----------
    symbol : str
        港股代码（未使用）。

    Returns
    -------
    None
    """
    logger.debug(f"yfinance HK 每日指标暂不支持: {symbol}")
    return None
