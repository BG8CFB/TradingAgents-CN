"""
Tushare HK 港股每日指标（日线复权数据）API — hk_daily_adj 接口封装。

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

_DOMAIN = "daily_indicators"
_SOURCE = "tushare_hk"


def _format_compact(date_str: str) -> str:
    """YYYY-MM-DD -> YYYYMMDD"""
    return str(date_str).replace("-", "") if date_str else ""


async def fetch_daily_adj(
    api,
    ts_code: str,
    start_date: str,
    end_date: str,
) -> Optional[pd.DataFrame]:
    """获取港股日线复权指标数据。

    Tushare HK 的 hk_daily_adj 接口返回 PE / PB / 市值 / 换手率等指标。

    Returns
    -------
    Optional[pd.DataFrame]
        原始 DataFrame，包含 ts_code / trade_date / pe / pb / total_mv / circ_mv 等。
    """
    return await call_tushare(
        api,
        "hk_daily_adj",
        _SOURCE,
        _DOMAIN,
        ts_code,
        ts_code=ts_code,
        start_date=_format_compact(start_date),
        end_date=_format_compact(end_date),
    )
