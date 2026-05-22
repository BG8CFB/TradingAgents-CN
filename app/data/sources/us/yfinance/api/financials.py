"""
yfinance US 美股财务数据 API
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


async def fetch_financials(symbol: str) -> Optional[pd.DataFrame]:
    """获取美股财务数据。

    通过 yf.Ticker(symbol).financials 获取利润表数据。

    Args:
        symbol: 股票代码（大写），如 "AAPL"

    Returns:
        财务数据 DataFrame，失败返回 None
    """
    try:
        import yfinance as yf

        ticker = symbol.upper().strip()

        def _fetch():
            t = yf.Ticker(ticker)
            return t.financials

        df = await asyncio.to_thread(_fetch)
        if df is not None and not df.empty:
            logger.info(f"yfinance-US 财务数据: {ticker} {len(df)} 条")
        return df
    except Exception as e:
        logger.debug(f"yfinance-US 获取财务数据失败 {symbol}: {e}")
        return None
