"""AKShare 交易日历 API

AKShare 新浪交易日历 (tool_trade_date_hist_sina) 返回全市场历史交易日，
不按交易所/日期范围过滤，因此在本地按日期范围切片。
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
_DOMAIN = "trade_calendar"


async def fetch_trade_calendar(
    exchange: str = "SSE",
    start_date: str = "1970-01-01",
    end_date: str = "2099-12-31",
) -> pd.DataFrame:
    """获取交易日历（AKShare 新浪接口）。

    Args:
        exchange: 交易所代码（SSE/SZSE），新浪接口仅含沪市，忽略此参数。
        start_date: 起始日期 YYYY-MM-DD
        end_date: 结束日期 YYYY-MM-DD

    Returns:
        DataFrame，列: cal_date, exchange, is_open

    Raises:
        NetworkError / DataFormatError / DataNotFoundError / DataSourceUnavailableError
    """
    try:
        import akshare as ak

        def _fetch():
            from app.data.sources.cn.akshare.api.anti_scraping import wait_rate_limit
            wait_rate_limit()
            return ak.tool_trade_date_hist_sina()

        df = await asyncio.to_thread(_fetch)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "akshare", _DOMAIN)
    except (KeyError, IndexError, AttributeError, ValueError) as exc:
        raise DataFormatError("akshare", _DOMAIN, f"{exc}")
    except Exception as exc:
        raise DataSourceUnavailableError("akshare", _DOMAIN, f"{exc}")

    if is_empty_result(df):
        raise DataNotFoundError("akshare", _DOMAIN, "无交易日历数据")

    # 新浪返回列名不稳定，取首个含 date 的列（否则取首列）作为交易日
    date_col = next((c for c in df.columns if "date" in str(c).lower()), df.columns[0])

    out = pd.DataFrame()
    out["cal_date"] = pd.to_datetime(df[date_col]).dt.strftime("%Y-%m-%d")
    out["exchange"] = exchange
    out["is_open"] = 1

    sd = pd.to_datetime(start_date).date()
    ed = pd.to_datetime(end_date).date()
    mask = (pd.to_datetime(out["cal_date"]).dt.date >= sd) & (
        pd.to_datetime(out["cal_date"]).dt.date <= ed
    )
    out = out[mask].reset_index(drop=True)
    return out
