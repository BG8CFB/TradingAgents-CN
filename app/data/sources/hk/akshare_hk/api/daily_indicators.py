"""
AKShare HK 港股每日指标 API — 暂不支持。
"""
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


async def fetch_daily_indicators(symbol: str) -> Optional[pd.DataFrame]:
    """获取港股每日指标。

    AKShare 对港股 PE / PB / 市值等指标的支持有限，
    当前返回 None。待后续 AKShare 提供对应接口后补充实现。

    Parameters
    ----------
    symbol : str
        5 位港股代码（未使用）。

    Returns
    -------
    None
    """
    logger.debug(f"AKShare HK 每日指标暂不支持: {symbol}")
    return None
