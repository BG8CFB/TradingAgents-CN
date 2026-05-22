"""
Tushare US 美股交易日历 API
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


async def fetch_trade_calendar(
    api,
    exchange: str = "NYSE",
    start_date: str = None,
    end_date: str = None,
) -> Optional[pd.DataFrame]:
    """获取美股交易日历。

    Args:
        api: tushare pro_api 实例
        exchange: 交易所代码，如 NYSE, NASDAQ
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)

    Returns:
        交易日历 DataFrame，失败返回 None
    """
    if api is None:
        return None
    try:
        params: dict = {"exchange": exchange}
        if start_date:
            params["start_date"] = start_date.replace("-", "")
        if end_date:
            params["end_date"] = end_date.replace("-", "")
        df = await asyncio.to_thread(api.us_tradecal, **params)
        if df is not None and not df.empty:
            logger.info(f"Tushare US 交易日历: {exchange} {len(df)} 条")
        return df
    except Exception as e:
        logger.error(f"Tushare US 获取交易日历失败: {e}")
        return None
