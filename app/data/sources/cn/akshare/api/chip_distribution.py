"""
AKShare 筹码分布 API — 通过 stock_cyq_em（东方财富每日筹码及胜率）获取。
作为 tushare cyq_perf 的备用源：当主源不可用时提供筹码成本 / 获利比例数据。
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

_DOMAIN = "chip_distribution"

# akshare stock_cyq_em 列名 → tushare cyq_perf 风格列名（缺失列自动忽略）
_COLUMN_MAPPER = {
    "日期": "trade_date",
    "收盘价": "close",
    "成本": "cost_avg",
    "平均成本": "cost_avg",
    "获利比例": "winner_rate",
}


async def fetch_chip_perf(
    symbol: str,
    start_date: str = None,
    end_date: str = None,
) -> pd.DataFrame:
    """获取每日筹码及胜率（AKShare 回退源）。

    返回与 tushare cyq_perf 同集合兼容的列：symbol / trade_date / close / cost_avg / winner_rate。
    """
    try:
        import akshare as ak

        from app.data.sources.cn.akshare.api.anti_scraping import wait_rate_limit

        code = str(symbol).zfill(6)

        def _fetch():
            wait_rate_limit()
            return ak.stock_cyq_em(symbol=code)

        df = await asyncio.to_thread(_fetch)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "akshare", _DOMAIN)
    except (KeyError, IndexError, AttributeError, ValueError) as exc:
        raise DataFormatError("akshare", _DOMAIN, f"symbol={symbol}: {exc}")
    except Exception as exc:
        raise DataSourceUnavailableError("akshare", _DOMAIN, f"symbol={symbol}: {exc}")

    if is_empty_result(df):
        raise DataNotFoundError("akshare", _DOMAIN, f"symbol={symbol} 无筹码数据")

    df = df.rename(columns=_COLUMN_MAPPER)

    # 日期归一化为 YYYYMMDD
    if "trade_date" in df.columns:
        df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.strftime("%Y%m%d")
        df = df.dropna(subset=["trade_date"])

    # 日期范围过滤（归一化 YYYY-MM-DD / YYYYMMDD）
    def _norm(s: str) -> str:
        return str(s).replace("-", "")

    if start_date:
        df = df[df["trade_date"] >= _norm(start_date)]
    if end_date:
        df = df[df["trade_date"] <= _norm(end_date)]

    if df.empty:
        raise DataNotFoundError("akshare", _DOMAIN, f"symbol={symbol} 过滤后无数据")

    df["symbol"] = code
    df["ts_code"] = code  # 供 generic_adapt 解析 symbol

    logger.info(f"AKShare 筹码胜率: {symbol} {len(df)} 条")
    return df
