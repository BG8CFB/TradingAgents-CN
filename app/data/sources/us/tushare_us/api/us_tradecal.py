"""
Tushare US 美股交易日历 API

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
_SOURCE = "tushare_us"


async def fetch_trade_calendar(
    api,
    exchange: str = "NYSE",
    start_date: str = None,
    end_date: str = None,
) -> Optional[pd.DataFrame]:
    """获取美股交易日历。

    Args:
        api: tushare pro_api 实例
        exchange: 交易所代码，如 NYSE, NASDAQ
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)

    Returns:
        交易日历 DataFrame，失败返回 None
    """
    params: dict = {"exchange": exchange}
    if start_date:
        params["start_date"] = start_date.replace("-", "")
    if end_date:
        params["end_date"] = end_date.replace("-", "")
    return await call_tushare(api, "us_tradecal", _SOURCE, _DOMAIN, exchange, **params)
