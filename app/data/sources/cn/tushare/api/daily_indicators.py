"""
Tushare 每日指标 API（PE/PB/市值/换手率等）

调用模板收敛在 app/data/sources/tushare_common/caller.py。
"""
import logging
from typing import Optional

import pandas as pd

from app.data.sources.tushare_common.caller import call_tushare

from .connection import TushareConnection

logger = logging.getLogger(__name__)

_DOMAIN = "daily_indicators"
_SOURCE = "tushare"

_DAILY_BASIC_FIELDS = (
    "ts_code,trade_date,total_mv,circ_mv,pe,pb,turnover_rate,volume_ratio,pe_ttm,pb_mrq,ps,ps_ttm"
)


async def fetch_daily_indicators(
    conn: TushareConnection, trade_date: str
) -> Optional[pd.DataFrame]:
    """获取全市场每日指标"""
    date_str = trade_date.replace("-", "")
    return await call_tushare(
        conn,
        "daily_basic",
        _SOURCE,
        _DOMAIN,
        f"trade_date={trade_date}",
        trade_date=date_str,
        fields=_DAILY_BASIC_FIELDS,
    )


async def fetch_daily_indicators_by_symbol(
    conn: TushareConnection, ts_code: str, start_date: str = None, end_date: str = None
) -> Optional[pd.DataFrame]:
    """获取单只股票每日指标"""
    params = {"ts_code": ts_code, "fields": _DAILY_BASIC_FIELDS}
    if start_date:
        params["start_date"] = start_date.replace("-", "")
    if end_date:
        params["end_date"] = end_date.replace("-", "")

    return await call_tushare(
        conn, "daily_basic", _SOURCE, _DOMAIN, f"ts_code={ts_code}", **params
    )
