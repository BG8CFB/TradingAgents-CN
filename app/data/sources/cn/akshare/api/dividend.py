"""AKShare 分红送配 API

AKShare stock_dividend_cninfo 按个股（巨潮历史分红）拉取分红方案，
对应 dividend 域。
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
_DOMAIN = "dividend"


async def fetch_dividend(ts_code: str = None) -> pd.DataFrame:
    """获取个股历史分红送配。

    Args:
        ts_code: 证券代码（如 600009.SH，自动去除交易所后缀）

    Raises:
        DataNotFoundError: 未提供代码或无数据
        NetworkError / DataFormatError / DataSourceUnavailableError
    """
    if not ts_code:
        raise DataNotFoundError("akshare", _DOMAIN, "未提供证券代码")

    code = str(ts_code).split(".")[0].zfill(6)
    try:
        import akshare as ak

        def _fetch():
            from app.data.sources.cn.akshare.api.anti_scraping import wait_rate_limit
            wait_rate_limit()
            return ak.stock_dividend_cninfo(symbol=code)

        df = await asyncio.to_thread(_fetch)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "akshare", _DOMAIN)
    except (KeyError, IndexError, AttributeError, ValueError) as exc:
        raise DataFormatError("akshare", _DOMAIN, f"code={code}: {exc}")
    except Exception as exc:
        raise DataSourceUnavailableError("akshare", _DOMAIN, f"code={code}: {exc}")

    if is_empty_result(df):
        raise DataNotFoundError("akshare", _DOMAIN, f"code={code} 无分红数据")

    df = df.copy()
    df["symbol"] = code
    return df.reset_index(drop=True)
