"""
Tushare 融资融券 API

接口: margin_detail (个股融资融券明细)
要求: >= 120 积分

调用模板收敛在 app/data/sources/tushare_common/caller.py。
"""
import logging
from typing import Optional

import pandas as pd

from app.data.sources.tushare_common.caller import call_tushare

from .connection import TushareConnection

logger = logging.getLogger(__name__)

_DOMAIN = "margin_trading"
_SOURCE = "tushare"


async def fetch_margin_detail(
    conn: TushareConnection,
    ts_code: str,
    start_date: str = None,
    end_date: str = None,
    limit: int = 60,
) -> Optional[pd.DataFrame]:
    """获取个股融资融券明细"""
    kwargs = {"ts_code": ts_code}
    if start_date:
        kwargs["start_date"] = str(start_date).replace("-", "")
    if end_date:
        kwargs["end_date"] = str(end_date).replace("-", "")
    if not start_date and not end_date:
        kwargs["limit"] = limit

    return await call_tushare(
        conn, "margin_detail", _SOURCE, _DOMAIN, f"ts_code={ts_code}", **kwargs
    )
