"""
Alpha Vantage US 美股日线行情 API
"""
import asyncio
import json
import logging
import os
import urllib.request
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

_AV_BASE_URL = "https://www.alphavantage.co/query"


async def fetch_daily_quotes(
    symbol: str,
    start_date: str,
    end_date: str,
) -> Optional[pd.DataFrame]:
    """获取美股日线行情。

    通过 Alpha Vantage TIME_SERIES_DAILY 端点获取全量日线数据，
    再按日期范围过滤。

    Args:
        symbol: 股票代码（大写），如 "AAPL"
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)

    Returns:
        日线行情 DataFrame，失败返回 None
    """
    api_key = os.getenv("ALPHA_VANTAGE_API_KEY", "")
    if not api_key:
        logger.debug("Alpha Vantage API Key 未配置")
        return None
    try:
        ticker = symbol.upper().strip()
        url = (
            f"{_AV_BASE_URL}?function=TIME_SERIES_DAILY"
            f"&symbol={ticker}&outputsize=full&apikey={api_key}"
        )

        def _fetch():
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            ts = data.get("Time Series (Daily)")
            if not ts:
                return None
            records = []
            for date_str, values in ts.items():
                if start_date <= date_str <= end_date:
                    records.append({
                        "trade_date": date_str,
                        "open": values.get("1. open"),
                        "high": values.get("2. high"),
                        "low": values.get("3. low"),
                        "close": values.get("4. close"),
                        "volume": values.get("5. volume"),
                        "symbol": ticker,
                    })
            return pd.DataFrame(records) if records else None

        df = await asyncio.to_thread(_fetch)
        if df is not None and not df.empty:
            logger.info(f"Alpha Vantage 日线行情: {ticker} {len(df)} 条")
        return df
    except Exception as e:
        logger.debug(f"Alpha Vantage 获取日线行情失败 {symbol}: {e}")
        return None
