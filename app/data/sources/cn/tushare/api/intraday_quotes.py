"""
Tushare 分钟线 API

接口: stk_mins
要求: >= 2000 积分, 限频 1 次/小时
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

from .connection import TushareConnection

logger = logging.getLogger(__name__)


async def fetch_intraday_quotes(
    conn: TushareConnection,
    ts_code: str,
    freq: str = "30min",
    limit: int = 500,
) -> Optional[pd.DataFrame]:
    """
    获取分钟级行情

    注意: stk_mins 限频 1次/小时，适合定时批量同步，不适合实时调用。
    """
    if not conn.is_available():
        return None

    freq_map = {"1min": "1", "5min": "5", "15min": "15", "30min": "30", "60min": "60"}
    freq_code = freq_map.get(freq, "30")

    try:
        df = await asyncio.to_thread(
            conn.api.stk_mins,
            ts_code=ts_code,
            freq=freq_code,
            limit=limit,
        )
        if df is None or df.empty:
            logger.debug(f"Tushare 分钟线为空: {ts_code}")
            return None
        logger.info(f"Tushare 分钟线: {ts_code} {len(df)} 条 ({freq})")
        return df
    except Exception as e:
        logger.error(f"Tushare 分钟线失败 {ts_code}: {e}")
        return None
