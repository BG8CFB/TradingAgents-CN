"""
Tushare HK 港股基础信息 API — hk_basic 接口封装。

调用模板（异常映射 map_tushare_code / 空结果判定）收敛在
app/data/sources/tushare_common/caller.py 的 call_tushare。

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
_SOURCE = "tushare_hk"


async def fetch_stock_list(api) -> Optional[pd.DataFrame]:
    """获取港股全部股票列表。

    Parameters
    ----------
    api : tushare.pro_api
        已初始化的 Tushare pro_api 实例（使用 TUSHARE_HK_TOKEN）。

    Returns
    -------
    Optional[pd.DataFrame]
        原始 DataFrame，包含 ts_code / name / industry 等字段。
    """
    return await call_tushare(api, "hk_basic", _SOURCE, _DOMAIN)
