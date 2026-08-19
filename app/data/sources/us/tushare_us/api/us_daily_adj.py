"""
Tushare US 美股日线行情（前复权）API

调用模板收敛在 app/data/sources/tushare_common/caller.py。

异常语义：NetworkError / RateLimitedError / TokenInvalidError /
InsufficientCreditsError / DataNotFoundError / DataSourceUnavailableError
由 call_tushare 统一抛出（内部经 map_tushare_code 错误码分类）。
"""
import logging
from typing import Optional

import pandas as pd

from app.data.sources.tushare_common.caller import call_tushare
from app.data.sources.us.tushare_us.code_resolver import get_us_ts_code

logger = logging.getLogger(__name__)

_DOMAIN = "daily_quotes"
_SOURCE = "tushare_us"


async def fetch_daily_adj(
    api,
    ts_code: str,
    start_date: str,
    end_date: str,
) -> Optional[pd.DataFrame]:
    """获取美股日线行情（前复权），同时包含每日指标数据（PE/PB/市值等）。"""
    if api is None:
        return None
    us_code = await get_us_ts_code(ts_code, api=api)
    return await call_tushare(
        api,
        "us_daily_adj",
        _SOURCE,
        _DOMAIN,
        us_code,
        ts_code=us_code,
        start_date=start_date.replace("-", ""),
        end_date=end_date.replace("-", ""),
    )
