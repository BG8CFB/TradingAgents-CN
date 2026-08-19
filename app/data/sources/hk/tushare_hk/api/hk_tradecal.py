"""
Tushare HK 港股交易日历 API — hk_tradecal 接口封装。

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

_DOMAIN = "trade_calendar"
_SOURCE = "tushare_hk"


def _format_compact(date_str: str) -> str:
    """YYYY-MM-DD -> YYYYMMDD"""
    return str(date_str).replace("-", "") if date_str else ""


async def fetch_trade_calendar(
    api,
    exchange: str = "HKEX",
    start_date: str = None,
    end_date: str = None,
) -> Optional[pd.DataFrame]:
    """获取港股交易日历。

    Returns
    -------
    Optional[pd.DataFrame]
        原始 DataFrame，包含 exchange / cal_date / is_open 等字段。
    """
    # 实测（2026-08，5000 积分）：hk_tradecal 传 exchange 参数服务端返回 0 行，
    # 不传才正常返回；与 us_tradecal（可传 exchange）行为不同。故不透传 exchange。
    params: dict = {}
    if start_date:
        params["start_date"] = _format_compact(start_date)
    if end_date:
        params["end_date"] = _format_compact(end_date)
    return await call_tushare(api, "hk_tradecal", _SOURCE, _DOMAIN, exchange, **params)
