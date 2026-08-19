"""
Tushare US 美股基础信息 API

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

_DOMAIN = "basic_info"
_SOURCE = "tushare_us"


async def fetch_stock_list(api) -> Optional[pd.DataFrame]:
    """获取美股股票列表（主要美股 + 中概股）。

    Args:
        api: tushare pro_api 实例

    Returns:
        包含美股基础信息的 DataFrame，失败返回 None
    """
    return await call_tushare(api, "us_basic", _SOURCE, _DOMAIN)
