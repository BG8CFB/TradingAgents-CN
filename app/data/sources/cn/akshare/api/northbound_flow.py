"""
AKShare 北向资金流向 API — 通过 stock_hsgt_hist_em（东方财富沪深港通历史）获取。

作为 tushare northbound_flow 的备用源：按日返回北向资金整体净流入 / 成交净买额等。
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
_DOMAIN = "northbound_flow"

_COLUMN_MAPPER = {
    "日期": "trade_date",
    "当日资金流入": "buy_in_amt",
    "当日成交净买额": "net_buy_amt",
    "当日余额": "balance",
    "历史累计净买额": "accum_buy_amt",
    "买入成交额": "buy_amt",
    "卖出成交额": "sell_amt",
    "领涨股-名称": "lead_stock",
    "领涨股-涨跌幅": "lead_pct",
}


def _norm_date(s: str) -> str:
    if not s:
        return None
    return str(s).replace("-", "")[:8]


async def fetch_northbound_flow(
    start_date: str = None,
    end_date: str = None,
) -> pd.DataFrame:
    """获取北向资金流向（AKShare 回退源）。"""
    try:
        import akshare as ak

        from app.data.sources.cn.akshare.api.anti_scraping import wait_rate_limit

        def _fetch():
            wait_rate_limit()
            return ak.stock_hsgt_hist_em(symbol="北向资金")

        df = await asyncio.to_thread(_fetch)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "akshare", _DOMAIN)
    except (KeyError, IndexError, AttributeError, ValueError) as exc:
        raise DataFormatError("akshare", _DOMAIN, f"{exc}")
    except Exception as exc:
        raise DataSourceUnavailableError("akshare", _DOMAIN, f"{exc}")

    if is_empty_result(df):
        raise DataNotFoundError("akshare", _DOMAIN, "无北向资金流向")

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
        raise DataNotFoundError("akshare", _DOMAIN, "过滤后无北向资金流向")

    df["symbol"] = "NORTHBOUND"
    df["ts_code"] = "NORTHBOUND"
    df["data_source"] = "akshare"

    logger.info(f"AKShare 北向资金流向: {len(df)} 条")
    return df
