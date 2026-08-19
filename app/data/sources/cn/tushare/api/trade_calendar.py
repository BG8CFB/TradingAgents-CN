"""
Tushare 交易日历 API

调用模板收敛在 app/data/sources/tushare_common/caller.py。
"""
import logging
from typing import Optional

import pandas as pd

from app.data.sources.tushare_common.caller import call_tushare

from .connection import TushareConnection

logger = logging.getLogger(__name__)

_DOMAIN = "trade_calendar"
_SOURCE = "tushare"


async def fetch_trade_calendar(
    conn: TushareConnection,
    exchange: str = "SSE",
    start_date: str = None,
    end_date: str = None,
) -> Optional[pd.DataFrame]:
    """获取交易日历"""
    params: dict = {"exchange": exchange}
    if start_date:
        params["start_date"] = start_date.replace("-", "")
    if end_date:
        params["end_date"] = end_date.replace("-", "")

    return await call_tushare(
        conn, "trade_cal", _SOURCE, _DOMAIN, f"exchange={exchange}", **params
    )
