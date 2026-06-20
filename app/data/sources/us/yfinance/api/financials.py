"""
yfinance US 美股财务数据 API
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

from app.data.sources.base.exceptions import (
    DataNotFoundError,
    DataSourceUnavailableError,
)
from app.data.sources.base.mappers import (
    is_empty_result,
    map_network_exception,
)

logger = logging.getLogger(__name__)

_DOMAIN = "financials"


async def fetch_financials(symbol: str) -> Optional[pd.DataFrame]:
    """获取美股财务数据。

    通过 yf.Ticker(symbol).financials 获取利润表数据。

    Args:
        symbol: 股票代码（大写），如 "AAPL"

    Returns:
        财务数据 DataFrame，失败返回 None

    Raises:
        NetworkError: 网络/超时异常（可重试）
        DataFormatError: yfinance 返回结构异常（不可重试）
        DataNotFoundError: 返回空数据（不可重试）
        DataSourceUnavailableError: 其他未知异常
    """
    try:
        import yfinance as yf

        ticker = symbol.upper().strip()

        def _fetch():
            t = yf.Ticker(ticker)
            return t.financials

        df = await asyncio.to_thread(_fetch)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "yfinance", _DOMAIN)
    except (KeyError, IndexError, ValueError, AttributeError) as exc:
        from app.data.sources.base.exceptions import DataFormatError
        raise DataFormatError("yfinance", _DOMAIN, f"symbol={symbol}: {exc}")
    except Exception as exc:
        raise DataSourceUnavailableError("yfinance", _DOMAIN, f"symbol={symbol}: {exc}")

    if is_empty_result(df):
        logger.warning(f"yfinance 返回空数据: {symbol} 财务")
        raise DataNotFoundError("yfinance", _DOMAIN, f"{symbol} 无财务数据")

    logger.info(f"yfinance 获取成功: {symbol} {len(df) if df is not None else 0} 条")
    return df
