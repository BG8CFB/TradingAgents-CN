"""
yfinance US 美股基础信息 API
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


async def fetch_basic_info(symbol: str) -> Optional[pd.DataFrame]:
    """获取美股基础信息。

    通过 yf.Ticker(symbol).info 获取，将 dict 包装为 DataFrame。

    Args:
        symbol: 股票代码（大写），如 "AAPL"

    Returns:
        包含基础信息的 DataFrame（单行），失败返回 None
    """
    try:
        import yfinance as yf

        ticker = symbol.upper().strip()

        def _fetch():
            t = yf.Ticker(ticker)
            info = t.info
            if not info:
                return None
            info["symbol"] = ticker
            return pd.DataFrame([info])

        df = await asyncio.to_thread(_fetch)
        if df is not None and not df.empty:
            logger.info(f"yfinance-US 基础信息: {ticker}")
        return df
    except Exception as e:
        logger.error(f"yfinance-US 获取基础信息失败 {symbol}: {e}")
        return None
