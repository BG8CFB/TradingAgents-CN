"""
Tushare 复权因子 API

调用模板收敛在 app/data/sources/tushare_common/caller.py。
"""
import logging
from typing import Optional

import pandas as pd

from app.data.sources.tushare_common.caller import call_tushare

from .connection import TushareConnection

logger = logging.getLogger(__name__)

_DOMAIN = "adj_factors"
_SOURCE = "tushare"


async def fetch_adj_factors(
    conn: TushareConnection,
    ts_code: str,
    start_date: str = None,
    end_date: str = None,
) -> Optional[pd.DataFrame]:
    """获取复权因子"""
    params: dict = {"ts_code": ts_code}
    if start_date:
        params["start_date"] = start_date.replace("-", "")
    if end_date:
        params["end_date"] = end_date.replace("-", "")

    return await call_tushare(
        conn, "adj_factor", _SOURCE, _DOMAIN, f"ts_code={ts_code}", **params
    )
