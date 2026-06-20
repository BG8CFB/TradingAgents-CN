"""
yfinance US 美股日线行情 API
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

_DOMAIN = "daily_quotes"


async def fetch_daily_quotes(
    symbol: str,
    start_date: str,
    end_date: str,
) -> Optional[pd.DataFrame]:
    """获取美股日线行情。

    通过 yf.Ticker(symbol).history() 获取，并添加 symbol 列。
    end_date 会自动 +1 天以确保包含当天数据。

    Args:
        symbol: 股票代码（大写），如 "AAPL"
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)

    Returns:
        日线行情 DataFrame（含 symbol 列），失败返回 None

    Raises:
        NetworkError: 网络/超时异常（可重试）
        DataFormatError: yfinance 返回结构异常（不可重试）
        DataNotFoundError: 返回空数据（不可重试）
        DataSourceUnavailableError: 其他未知异常
    """
    try:
        import yfinance as yf

        ticker = symbol.upper().strip()
        end = pd.to_datetime(end_date) + pd.DateOffset(days=1)

        def _fetch():
            t = yf.Ticker(ticker)
            df = t.history(start=start_date, end=end.strftime("%Y-%m-%d"))
            if df is not None and not df.empty:
                df["symbol"] = ticker
            return df

        df = await asyncio.to_thread(_fetch)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "yfinance", _DOMAIN)
    except (KeyError, IndexError, ValueError, AttributeError) as exc:
        from app.data.sources.base.exceptions import DataFormatError
        raise DataFormatError("yfinance", _DOMAIN, f"symbol={symbol}: {exc}")
    except Exception as exc:
        raise DataSourceUnavailableError("yfinance", _DOMAIN, f"symbol={symbol}: {exc}")

    if is_empty_result(df):
        logger.warning(f"yfinance 返回空数据: {symbol} 日线行情")
        raise DataNotFoundError("yfinance", _DOMAIN, f"{symbol} 无数据")

    logger.info(f"yfinance 获取成功: {symbol} {len(df) if df is not None else 0} 条")
    return df
