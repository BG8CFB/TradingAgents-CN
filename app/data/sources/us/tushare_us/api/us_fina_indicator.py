"""
Tushare US 美股财务指标 API

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

_DOMAIN = "fina_indicator"
_SOURCE = "tushare_us"


async def fetch_fina_indicator(
    api,
    ts_code: str,
) -> Optional[pd.DataFrame]:
    """获取美股财务指标数据。"""
    if api is None:
        return None
    us_code = await get_us_ts_code(ts_code, api=api)
    return await call_tushare(
        api, "us_fina_indicator", _SOURCE, _DOMAIN, us_code, ts_code=us_code
    )
