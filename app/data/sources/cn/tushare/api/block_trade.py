"""
Tushare 大宗交易 API

接口: block_trade (大宗交易明细)
要求: >= 120 积分

调用模板收敛在 app/data/sources/tushare_common/caller.py。
"""
import logging
from typing import Optional

import pandas as pd

from app.data.sources.tushare_common.caller import call_tushare

from .connection import TushareConnection

logger = logging.getLogger(__name__)

_DOMAIN = "block_trade"
_SOURCE = "tushare"


async def fetch_block_trade(
    conn: TushareConnection,
    ts_code: str = None,
    start_date: str = None,
    end_date: str = None,
    limit: int = 500,
) -> Optional[pd.DataFrame]:
    """获取大宗交易数据"""
    kwargs = {}
    if ts_code:
        kwargs["ts_code"] = ts_code
    if start_date:
        kwargs["start_date"] = str(start_date).replace("-", "")
    if end_date:
        kwargs["end_date"] = str(end_date).replace("-", "")
    if not start_date and not end_date and not ts_code:
        kwargs["limit"] = limit

    return await call_tushare(conn, "block_trade", _SOURCE, _DOMAIN, **kwargs)
