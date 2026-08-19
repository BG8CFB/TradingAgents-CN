"""
Tushare HK 港股财务指标 API — hk_fina_indicator 接口封装。

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

_DOMAIN = "fina_indicator"
_SOURCE = "tushare_hk"


async def fetch_fina_indicator(
    api,
    ts_code: str,
) -> Optional[pd.DataFrame]:
    """获取港股财务指标（ROE / EPS / BPS 等）。

    Returns
    -------
    Optional[pd.DataFrame]
        原始 DataFrame，包含 ts_code / end_date / roe / eps / bps 等字段。
    """
    return await call_tushare(
        api, "hk_fina_indicator", _SOURCE, _DOMAIN, ts_code, ts_code=ts_code
    )
