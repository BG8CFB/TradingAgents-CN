"""
AKShare 涨跌停 API — 通过 stock_zt_pool_em（东方财富涨停股池）获取。

作为 tushare price_limit 的备用源：按交易日返回涨停个股池（价格 / 连板数 / 行业等）。
"""
import asyncio
import logging
from datetime import date

import pandas as pd

from app.data.sources.base.exceptions import (
    DataFormatError,
    DataNotFoundError,
    DataSourceUnavailableError,
)
from app.data.sources.base.mappers import is_empty_result, map_network_exception

logger = logging.getLogger(__name__)
_DOMAIN = "price_limit"

_COLUMN_MAPPER = {
    "代码": "ts_code",
    "名称": "name",
    "最新价": "price",
    "涨跌幅": "pct_chg",
    "成交额": "amount",
    "流通市值": "circ_mv",
    "总市值": "total_mv",
    "换手率": "turnover_rate",
    "连板数": "limit_days",
    "首次封板时间": "first_time",
    "最后封板时间": "last_time",
    "封板资金": "lock_amount",
    "炸板次数": "open_times",
    "所属行业": "industry",
    "涨停统计": "limit_stats",
}


def _norm_date(s: str) -> str:
    if not s:
        return None
    return str(s).replace("-", "")[:8]


async def fetch_price_limit(trade_date: str = None) -> pd.DataFrame:
    """获取涨跌停个股池（AKShare 回退源）。"""
    qdate = _norm_date(trade_date) or date.today().strftime("%Y%m%d")

    try:
        import akshare as ak

        from app.data.sources.cn.akshare.api.anti_scraping import wait_rate_limit

        def _fetch():
            wait_rate_limit()
            return ak.stock_zt_pool_em(date=qdate)

        df = await asyncio.to_thread(_fetch)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "akshare", _DOMAIN)
    except (KeyError, IndexError, AttributeError, ValueError) as exc:
        raise DataFormatError("akshare", _DOMAIN, f"date={qdate}: {exc}")
    except Exception as exc:
        raise DataSourceUnavailableError("akshare", _DOMAIN, f"date={qdate}: {exc}")

    if is_empty_result(df):
        raise DataNotFoundError("akshare", _DOMAIN, f"date={qdate} 无涨跌停数据")

    df = df.rename(columns=_COLUMN_MAPPER)

    if "ts_code" in df.columns:
        df["ts_code"] = df["ts_code"].astype(str).str.zfill(6)
        df["symbol"] = df["ts_code"]
    df["trade_date"] = qdate
    df["data_source"] = "akshare"

    logger.info(f"AKShare 涨跌停: {qdate} {len(df)} 条")
    return df
