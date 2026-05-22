"""
yfinance US 美股日线行情 API
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


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
        if df is not None and not df.empty:
            logger.info(f"yfinance-US 日线行情: {ticker} {len(df)} 条")
        return df
    except Exception as e:
        logger.error(f"yfinance-US 获取日线行情失败 {symbol}: {e}")
        return None
