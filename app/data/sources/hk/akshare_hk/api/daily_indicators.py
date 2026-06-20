"""
AKShare HK 港股每日指标 API — 暂不支持。
"""
import logging
from typing import Optional

import pandas as pd

from app.data.sources.base.exceptions import DataNotFoundError

logger = logging.getLogger(__name__)

_DOMAIN = "daily_indicators"


async def fetch_daily_indicators(symbol: str) -> Optional[pd.DataFrame]:
    """获取港股每日指标。

    AKShare 对港股 PE / PB / 市值等指标的支持有限，
    当前接口未实现。待后续 AKShare 提供对应接口后补充实现。

    暂以 DataNotFoundError 抛出，便于上层 fallback 路由自动切换到其他数据源。

    Raises
    ------
    DataNotFoundError
        接口未实现，无数据。

    Parameters
    ----------
    symbol : str
        5 位港股代码（未使用）。

    Returns
    -------
    None
    """
    logger.debug(f"akshare_hk 每日指标暂不支持: {symbol}")
    raise DataNotFoundError("akshare_hk", _DOMAIN, f"{symbol} 接口未实现")
