"""
yfinance HK 港股日线行情 API — Ticker.history() 接口封装。
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


def _to_yfinance_symbol(symbol: str) -> str:
    """港股代码转 yfinance 格式: 00700 / 0700.HK → 0700.HK"""
    code = str(symbol).replace(".HK", "").lstrip("0").zfill(4)
    return f"{code}.HK"


async def fetch_daily_quotes(
    symbol: str,
    start_date: str,
    end_date: str,
) -> Optional[pd.DataFrame]:
    """获取港股日线行情。

    yfinance history() 返回 OHLCV 数据，索引为 DatetimeIndex。

    Parameters
    ----------
    symbol : str
        港股代码，支持 "00700" / "0700.HK" 等格式。
    start_date : str
        起始日期，格式 YYYY-MM-DD。
    end_date : str
        截止日期，格式 YYYY-MM-DD。

    Returns
    -------
    Optional[pd.DataFrame]
        原始 DataFrame，索引为日期，包含 Open / High / Low / Close / Volume 等字段。
    """
    try:
        import yfinance as yf
        hk_symbol = _to_yfinance_symbol(symbol)
        # yfinance end_date 是 exclusive，需 +1 天
        end = pd.to_datetime(end_date) + pd.DateOffset(days=1)
        end_str = end.strftime("%Y-%m-%d")

        def _fetch():
            ticker = yf.Ticker(hk_symbol)
            return ticker.history(start=start_date, end=end_str)

        df = await asyncio.to_thread(_fetch)
        if df is not None and not df.empty:
            logger.info(f"yfinance HK 获取行情: {symbol} {len(df)} 条")
        return df
    except Exception as e:
        logger.error(f"yfinance HK 获取行情失败: {symbol} - {e}")
        return None
