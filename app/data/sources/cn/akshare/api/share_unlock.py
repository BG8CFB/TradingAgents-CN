"""
AKShare 限售股解禁 API — 通过 stock_restricted_release_summary_em（东方财富解禁汇总）获取。

作为 tushare share_unlock 的备用源：按日返回全市场解禁汇总（家数 / 数量 / 市值）。
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
_DOMAIN = "share_unlock"

_COLUMN_MAPPER = {
    "解禁时间": "trade_date",
    "当日解禁股票家数": "count",
    "实际解禁数量": "actual_shares",
    "实际解禁市值": "actual_mv",
    "解禁数量": "lift_shares",
    "沪深300指数": "index",
    "沪深300指数涨跌幅": "index_pct",
}


def _norm_date(s: str) -> str:
    if not s:
        return None
    return str(s).replace("-", "")[:8]


async def fetch_share_unlock(
    start_date: str = None,
    end_date: str = None,
) -> pd.DataFrame:
    """获取限售股解禁（AKShare 回退源）。"""
    sd = _norm_date(start_date) or "19900101"
    ed = _norm_date(end_date) or "20991231"

    try:
        import akshare as ak

        from app.data.sources.cn.akshare.api.anti_scraping import wait_rate_limit

        def _fetch():
            wait_rate_limit()
            return ak.stock_restricted_release_summary_em(
                symbol="全部股票", start_date=sd, end_date=ed
            )

        df = await asyncio.to_thread(_fetch)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "akshare", _DOMAIN)
    except (KeyError, IndexError, AttributeError, ValueError) as exc:
        raise DataFormatError("akshare", _DOMAIN, f"{exc}")
    except Exception as exc:
        raise DataSourceUnavailableError("akshare", _DOMAIN, f"{exc}")

    if is_empty_result(df):
        raise DataNotFoundError("akshare", _DOMAIN, "无解禁数据")

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
        raise DataNotFoundError("akshare", _DOMAIN, "过滤后无解禁数据")

    df["symbol"] = "UNLOCK"
    df["ts_code"] = "UNLOCK"
    df["data_source"] = "akshare"

    logger.info(f"AKShare 限售股解禁: {len(df)} 条")
    return df
