"""yfinance US 美股每日指标 API

yfinance 通过 Ticker.info 提供部分静态指标（PE/PB/市值等），
作为 daily_indicators 的近似数据源。
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


async def fetch_daily_indicators(symbol: str) -> Optional[pd.DataFrame]:
    """获取美股每日指标数据（PE/PB/市值等）。

    通过 yf.Ticker(symbol).info 获取静态指标，
    包装为单行 DataFrame，trade_date 设为当天。

    Args:
        symbol: 股票代码（大写），如 "AAPL"

    Returns:
        包含每日指标的 DataFrame（单行），失败返回 None
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
        if df is not None and not df.empty:
            logger.debug(f"yfinance-US 每日指标: {ticker}")
        return df
    except Exception as e:
        logger.debug(f"yfinance-US 每日指标失败 {symbol}: {e}")
        return None
