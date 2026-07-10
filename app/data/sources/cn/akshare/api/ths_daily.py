"""
AKShare 同花顺板块日线 API — 通过 stock_board_concept_hist_em / stock_board_industry_hist_em 获取。

作为 tushare ths_daily 的备用源。akshare 按板块名称（而非 ts_code）查询，因此仅在
提供板块名称（symbol）时可回退；全市场批量模式（symbol=None）下无可用数据，
抛出 DataNotFoundError 由路由器降级到主源 tushare。
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
_DOMAIN = "ths_daily"

_COLUMN_MAPPER = {
    "日期": "trade_date",
    "开盘": "open",
    "收盘": "close",
    "最高": "high",
    "最低": "low",
    "成交量": "volume",
    "成交额": "amount",
    "振幅": "amplitude",
    "涨跌幅": "pct_chg",
    "涨跌额": "change",
    "换手率": "turnover_rate",
}


def _norm_date(s: str) -> str:
    if not s:
        return None
    return str(s).replace("-", "")[:8]


async def fetch_ths_daily(
    symbol: str = None,
    start_date: str = None,
    end_date: str = None,
) -> pd.DataFrame:
    """获取同花顺板块日线（AKShare 回退源）。symbol 为板块名称。"""
    if not symbol:
        raise DataNotFoundError("akshare", _DOMAIN, "ths_daily 需板块名称，无法全市场回退")

    sd = _norm_date(start_date) or "19900101"
    ed = _norm_date(end_date) or "20991231"

    try:
        import akshare as ak

        from app.data.sources.cn.akshare.api.anti_scraping import wait_rate_limit

        def _fetch():
            wait_rate_limit()
            try:
                return ak.stock_board_concept_hist_em(
                    symbol=symbol, period="daily", start_date=sd, end_date=ed
                )
            except Exception:
                return ak.stock_board_industry_hist_em(
                    symbol=symbol, start_date=sd, end_date=ed
                )

        df = await asyncio.to_thread(_fetch)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "akshare", _DOMAIN)
    except (KeyError, IndexError, AttributeError, ValueError) as exc:
        raise DataFormatError("akshare", _DOMAIN, f"symbol={symbol}: {exc}")
    except Exception as exc:
        raise DataSourceUnavailableError("akshare", _DOMAIN, f"symbol={symbol}: {exc}")

    if is_empty_result(df):
        raise DataNotFoundError("akshare", _DOMAIN, f"symbol={symbol} 无板块日线")

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
    df["symbol"] = symbol
    df["name"] = symbol
    df["data_source"] = "akshare"

    logger.info(f"AKShare 板块日线: {symbol} {len(df)} 条")
    return df
