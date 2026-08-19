"""
Tushare HK 港股日线行情 API — hk_daily 接口封装。

调用模板（异常映射 map_tushare_code / 空结果判定）收敛在
app/data/sources/tushare_common/caller.py 的 call_tushare；
错误分类经由 call_tushare 内部的 map_tushare_code 完成。

异常语义：NetworkError / RateLimitedError / TokenInvalidError /
InsufficientCreditsError / DataNotFoundError / DataSourceUnavailableError
由 call_tushare 统一抛出（内部经 map_tushare_code 错误码分类）。
"""
import logging
from typing import Optional

import pandas as pd

from app.data.sources.tushare_common.caller import call_tushare

logger = logging.getLogger(__name__)

_DOMAIN = "daily_quotes"
_SOURCE = "tushare_hk"


def _format_compact(date_str: str) -> str:
    """YYYY-MM-DD -> YYYYMMDD"""
    return str(date_str).replace("-", "") if date_str else ""


async def fetch_daily_quotes(
    api,
    ts_code: str,
    start_date: str,
    end_date: str,
) -> Optional[pd.DataFrame]:
    """获取港股日线行情（未复权）。

    Parameters
    ----------
    api : tushare.pro_api
        已初始化的 Tushare pro_api 实例。
    ts_code : str
        Tushare 格式港股代码，如 "0700.HK"。
    start_date : str
        起始日期，格式 YYYY-MM-DD 或 YYYYMMDD。
    end_date : str
        截止日期，格式 YYYY-MM-DD 或 YYYYMMDD。

    Returns
    -------
    Optional[pd.DataFrame]
        原始 DataFrame，包含 ts_code / trade_date / open / high / low / close / vol 等。
    """
    start_str = _format_compact(start_date)
    end_str = _format_compact(end_date)
    return await call_tushare(
        api,
        "hk_daily",
        _SOURCE,
        _DOMAIN,
        f"ts_code={ts_code} {start_str}-{end_str}",
        ts_code=ts_code,
        start_date=start_str,
        end_date=end_str,
    )
