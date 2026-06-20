"""
yfinance HK 港股每日指标 API — 暂不支持独立指标接口。
"""
import logging
from typing import Optional

import pandas as pd

from app.data.sources.base.exceptions import DataNotFoundError

logger = logging.getLogger(__name__)

_DOMAIN = "daily_indicators"


async def fetch_daily_indicators(symbol: str) -> Optional[pd.DataFrame]:
    """获取港股每日指标。

    yfinance 不提供独立的每日指标（PE/PB/市值等）批量接口，
    部分指标可从 Ticker.info 中获取但非时间序列。

    暂以 DataNotFoundError 抛出，便于上层 fallback 路由自动切换到其他数据源。
    如需指标数据请使用 Tushare HK 或 AKShare HK。

    Raises
    ------
    DataNotFoundError
        接口未实现，无数据。

    Parameters
    ----------
    symbol : str
        港股代码（未使用）。

    Returns
    -------
    None
    """
    logger.debug(f"yfinance_hk 每日指标暂不支持: {symbol}")
    raise DataNotFoundError("yfinance_hk", _DOMAIN, f"{symbol} 接口未实现")
