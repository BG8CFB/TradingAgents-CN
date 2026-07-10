"""
AKShare 指数每日指标 API — 通过 stock_zh_index_value_csindex（中证指数估值）获取。

作为 tushare index_dailybasic 的备用源：市盈率 / 股息率等。
akshare 该接口按指数代码返回全历史，无日期范围参数，由本函数做日期过滤。
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
_DOMAIN = "index_dailybasic"

_COLUMN_MAPPER = {
    "日期": "trade_date",
    "指数代码": "ts_code",
    "指数中文全称": "full_name",
    "指数中文简称": "short_name",
    "市盈率1": "pe",
    "市盈率2": "pe2",
    "股息率1": "dv_ratio",
    "股息率2": "dv_ratio2",
}


def _norm_date(s: str) -> str:
    if not s:
        return None
    return str(s).replace("-", "")[:8]


async def fetch_index_dailybasic(
    symbol: str,
    start_date: str = None,
    end_date: str = None,
) -> pd.DataFrame:
    """获取指数每日指标（AKShare 回退源）。"""
    code = str(symbol).split(".")[0] if symbol else ""
    if not code:
        raise DataNotFoundError("akshare", _DOMAIN, f"symbol={symbol} 无效")

    try:
        import akshare as ak

        from app.data.sources.cn.akshare.api.anti_scraping import wait_rate_limit

        def _fetch():
            wait_rate_limit()
            return ak.stock_zh_index_value_csindex(symbol=code)

        df = await asyncio.to_thread(_fetch)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "akshare", _DOMAIN)
    except (KeyError, IndexError, AttributeError, ValueError) as exc:
        raise DataFormatError("akshare", _DOMAIN, f"symbol={symbol}: {exc}")
    except Exception as exc:
        raise DataSourceUnavailableError("akshare", _DOMAIN, f"symbol={symbol}: {exc}")

    if is_empty_result(df):
        raise DataNotFoundError("akshare", _DOMAIN, f"symbol={symbol} 无指数每日指标")

    df = df.rename(columns=_COLUMN_MAPPER)

    if "trade_date" in df.columns:
        df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.strftime("%Y%m%d")
        df = df.dropna(subset=["trade_date"])

    def _n(s: str) -> str:
        return str(s).replace("-", "")

    if start_date:
        df = df[df["trade_date"] >= _n(start_date)]
    if end_date:
        df = df[df["trade_date"] <= _n(end_date)]

    if df.empty:
        raise DataNotFoundError("akshare", _DOMAIN, f"symbol={symbol} 过滤后无数据")

    df["ts_code"] = symbol
    df["symbol"] = code
    df["data_source"] = "akshare"

    logger.info(f"AKShare 指数每日指标: {symbol} {len(df)} 条")
    return df
