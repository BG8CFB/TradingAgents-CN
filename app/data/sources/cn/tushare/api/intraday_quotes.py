"""
Tushare 分钟线 API

接口: stk_mins
要求: >= 2000 积分, 限频 1 次/小时

调用模板收敛在 app/data/sources/tushare_common/caller.py。
"""
import logging
from typing import Optional

import pandas as pd

from app.data.sources.tushare_common.caller import call_tushare

from .connection import TushareConnection

logger = logging.getLogger(__name__)

_DOMAIN = "intraday_quotes"
_SOURCE = "tushare"


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
    freq_map = {"1min": "1", "5min": "5", "15min": "15", "30min": "30", "60min": "60"}
    freq_code = freq_map.get(freq, "30")

    return await call_tushare(
        conn,
        "stk_mins",
        _SOURCE,
        _DOMAIN,
        f"ts_code={ts_code} ({freq})",
        ts_code=ts_code,
        freq=freq_code,
        limit=limit,
    )
