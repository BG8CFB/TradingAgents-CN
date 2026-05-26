"""
Finnhub US 美股实时行情快照 API
"""
import asyncio
import logging
import os
from typing import Optional

import pandas as pd

from app.core.env import get_env

logger = logging.getLogger(__name__)


async def fetch_quote(symbol: str) -> Optional[pd.DataFrame]:
    """获取美股实时行情快照。

    通过 finnhub.Client.quote(symbol) 获取，包装为 DataFrame。

    Args:
        symbol: 股票代码（大写），如 "AAPL"

    Returns:
        行情快照 DataFrame（单行），失败返回 None
    """
    api_key = get_env("FINNHUB_API_KEY", "")
    if not api_key:
        logger.debug("Finnhub API Key 未配置")
        return None
    try:
        import finnhub

        ticker = symbol.upper().strip()

        def _fetch():
            client = finnhub.Client(api_key=api_key)
            quote = client.quote(ticker)
            return quote if quote and "c" in quote else None

        quote = await asyncio.to_thread(_fetch)
        if not quote:
            return None

        df = pd.DataFrame([{
            "symbol": ticker,
            "price": quote.get("c"),
            "change": quote.get("d"),
            "pct_change": quote.get("dp"),
            "volume": quote.get("v"),
            "high": quote.get("h"),
            "low": quote.get("l"),
            "open": quote.get("o"),
            "previous_close": quote.get("pc"),
        }])
        logger.info(f"Finnhub-US 快照: {ticker}")
        return df
    except Exception as e:
        logger.debug(f"Finnhub-US 获取快照失败 {symbol}: {e}")
        return None
