"""
Tushare HK 港股南向持股 API — hk_hold 接口封装。

调用模板收敛在 app/data/sources/tushare_common/caller.py。

异常语义：NetworkError / RateLimitedError / TokenInvalidError /
InsufficientCreditsError / DataNotFoundError / DataSourceUnavailableError
由 call_tushare 统一抛出（内部经 map_tushare_code 错误码分类）。
"""
import logging
from typing import Optional

import pandas as pd

from app.data.sources.tushare_common.caller import call_tushare

logger = logging.getLogger(__name__)

_DOMAIN = "southbound_holding"
_SOURCE = "tushare_hk"


def _format_compact(date_str: str) -> str:
    """YYYY-MM-DD -> YYYYMMDD"""
    return str(date_str).replace("-", "") if date_str else ""


async def fetch_southbound_holdings(
    api,
    ts_code: str = None,
    start_date: str = None,
    end_date: str = None,
) -> Optional[pd.DataFrame]:
    """获取港股通南向持股数据。

    Parameters
    ----------
    ts_code : str, optional
        Tushare 格式港股代码，如 "0700.HK"。不传则返回全市场。
    start_date / end_date : str, optional
        起始/截止日期，格式 YYYY-MM-DD 或 YYYYMMDD。

    Returns
    -------
    Optional[pd.DataFrame]
        原始 DataFrame，包含 ts_code / trade_date / vol / amount 等字段。
    """
    params: dict = {}
    if ts_code:
        params["ts_code"] = ts_code
    if start_date:
        params["start_date"] = _format_compact(start_date)
    if end_date:
        params["end_date"] = _format_compact(end_date)
    return await call_tushare(
        api, "hk_hold", _SOURCE, _DOMAIN, ts_code or "全市场", **params
    )
