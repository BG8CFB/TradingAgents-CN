"""yfinance US 美股每日指标 API

yfinance 通过 Ticker.info 提供部分静态指标（PE/PB/市值等），
作为 daily_indicators 的近似数据源。
"""
import asyncio
import logging
from datetime import datetime
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

_DOMAIN = "daily_indicators"


async def fetch_daily_indicators(symbol: str) -> Optional[pd.DataFrame]:
    """获取美股每日指标数据（PE/PB/市值等）。

    通过 yf.Ticker(symbol).info 获取静态指标，
    包装为单行 DataFrame，trade_date 设为当天。

    Args:
        symbol: 股票代码（大写），如 "AAPL"

    Returns:
        包含每日指标的 DataFrame（单行），失败返回 None

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
            info = t.info
            if not info:
                return None
            record = {
                "symbol": ticker,
                "trade_date": datetime.now().strftime("%Y-%m-%d"),
                "pe_ttm": info.get("trailingPE"),
                "pb": info.get("priceToBook"),
                "ps_ttm": info.get("priceToSalesTrailing12Months"),
                "dividend_yield": info.get("dividendYield"),
                "market_cap": info.get("marketCap"),
                "shares_outstanding": info.get("sharesOutstanding"),
                "float_shares": info.get("floatShares"),
            }
            return pd.DataFrame([record])

        df = await asyncio.to_thread(_fetch)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "yfinance", _DOMAIN)
    except (KeyError, IndexError, ValueError, AttributeError) as exc:
        from app.data.sources.base.exceptions import DataFormatError
        raise DataFormatError("yfinance", _DOMAIN, f"symbol={symbol}: {exc}")
    except Exception as exc:
        raise DataSourceUnavailableError("yfinance", _DOMAIN, f"symbol={symbol}: {exc}")

    if is_empty_result(df):
        logger.warning(f"yfinance 返回空数据: {symbol} 指标")
        raise DataNotFoundError("yfinance", _DOMAIN, f"{symbol} 无指标数据")

    logger.debug(f"yfinance 获取成功: {symbol} 指标")
    return df
