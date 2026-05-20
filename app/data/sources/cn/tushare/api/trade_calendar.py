"""
Tushare 交易日历 API
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

from .connection import TushareConnection

logger = logging.getLogger(__name__)


async def fetch_trade_calendar(
    conn: TushareConnection,
    exchange: str = "SSE",
    start_date: str = None,
    end_date: str = None,
) -> Optional[pd.DataFrame]:
    """获取交易日历"""
    if not conn.is_available():
        return None
    try:
        params: dict = {"exchange": exchange}
        if start_date:
            params["start_date"] = start_date.replace("-", "")
        if end_date:
            params["end_date"] = end_date.replace("-", "")
        df = await asyncio.to_thread(conn.api.trade_cal, **params)
        if df is not None and not df.empty:
            logger.info(f"Tushare 交易日历: {exchange} {len(df)} 条")
        return df
    except Exception as e:
        logger.error(f"Tushare 获取交易日历失败: {e}")
        return None
