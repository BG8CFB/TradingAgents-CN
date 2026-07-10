"""AKShare 申万行业指数日线 API

AKShare index_hist_sw 按申万指数代码（如 801030）拉取日线，路由层
调用 sw_daily 时未携带指数代码，故未提供代码时视为无数据（降级跳过）。
"""
import asyncio
import logging

import pandas as pd

from app.data.sources.base.exceptions import (
    DataFormatError,
    DataNotFoundError,
    DataSourceUnavailableError,
)
from app.data.sources.base.mappers import is_empty_result, map_network_exception

logger = logging.getLogger(__name__)
_DOMAIN = "sw_daily"


async def fetch_sw_daily(
    ts_code: str = None,
    trade_date: str = None,
    start_date: str = None,
    end_date: str = None,
) -> pd.DataFrame:
    """获取申万行业指数日线。

    Args:
        ts_code: 申万指数代码（如 801030），路由层未提供时返回无数据。
        trade_date: 单日（未使用，index_hist_sw 返回区间）
        start_date / end_date: 日期范围过滤

    Raises:
        DataNotFoundError: 未提供指数代码或无数据
        NetworkError / DataFormatError / DataSourceUnavailableError
    """
    if not ts_code:
        raise DataNotFoundError("akshare", _DOMAIN, "未提供申万指数代码")

    code = str(ts_code).split(".")[0].zfill(6)
    try:
        import akshare as ak

        def _fetch():
            from app.data.sources.cn.akshare.api.anti_scraping import wait_rate_limit
            wait_rate_limit()
            return ak.index_hist_sw(symbol=code, period="day")

        df = await asyncio.to_thread(_fetch)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "akshare", _DOMAIN)
    except (KeyError, IndexError, AttributeError, ValueError) as exc:
        raise DataFormatError("akshare", _DOMAIN, f"code={code}: {exc}")
    except Exception as exc:
        raise DataSourceUnavailableError("akshare", _DOMAIN, f"code={code}: {exc}")

    if is_empty_result(df):
        raise DataNotFoundError("akshare", _DOMAIN, f"code={code} 无数据")

    # 按日期范围过滤（AKShare 列名可能为中文"日期"或英文"date"）
    date_col = next(
        (c for c in df.columns if "date" in str(c).lower() or str(c) == "日期"),
        None,
    )
    if date_col and (start_date or end_date):
        d = pd.to_datetime(df[date_col])
        if start_date:
            df = df[d >= pd.to_datetime(start_date)]
        if end_date:
            df = df[d <= pd.to_datetime(end_date)]

    df = df.copy()
    df["symbol"] = code
    return df.reset_index(drop=True)
