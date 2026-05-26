"""
Finnhub US 美股新闻 API
"""
import asyncio
import logging
import os
from typing import Optional

import pandas as pd

from app.core.env import get_env

logger = logging.getLogger(__name__)


async def fetch_news(
    symbol: str,
    start_date: str,
    end_date: str,
) -> Optional[pd.DataFrame]:
    """获取美股公司新闻。

    通过 finnhub.Client.company_news(symbol, _from, to) 获取。
    最多返回 50 条新闻。

    Args:
        symbol: 股票代码（大写），如 "AAPL"
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)

    Returns:
        新闻 DataFrame，失败返回 None
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
            news = client.company_news(ticker, _from=start_date, to=end_date)
            return pd.DataFrame(news[:50]) if news else None

        df = await asyncio.to_thread(_fetch)
        if df is not None and not df.empty:
            logger.info(f"Finnhub-US 新闻: {ticker} {len(df)} 条")
        return df
    except Exception as e:
        logger.debug(f"Finnhub-US 获取新闻失败 {symbol}: {e}")
        return None
