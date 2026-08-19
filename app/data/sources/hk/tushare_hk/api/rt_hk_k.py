"""
Tushare HK 港股实时行情 API — rt_hk_k 接口封装。

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

_DOMAIN = "realtime_quotes"
_SOURCE = "tushare_hk"


async def fetch_realtime_quotes(api) -> Optional[pd.DataFrame]:
    """获取港股全市场实时行情快照。

    Returns
    -------
    Optional[pd.DataFrame]
        原始 DataFrame，包含 ts_code / price / volume / amount 等字段。
    """
    return await call_tushare(api, "rt_hk_k", _SOURCE, _DOMAIN)
