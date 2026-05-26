"""
AKShare 日线行情 API
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


async def fetch_daily_quotes(
    code: str,
    start_date: str,
    end_date: str,
    period: str = "daily",
    adjust: str = "qfq",
) -> Optional[pd.DataFrame]:
    """获取 A 股历史行情"""
    try:
        import akshare as ak

        period_map = {"daily": "daily", "weekly": "weekly", "monthly": "monthly"}
        ak_period = period_map.get(period, "daily")

        def _fetch():
            from app.data.sources.cn.akshare.api.anti_scraping import wait_rate_limit
            wait_rate_limit()
            return ak.stock_zh_a_hist(
                symbol=code, period=ak_period,
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
                adjust=adjust,
            )

        df = await asyncio.to_thread(_fetch)
        if df is not None and not df.empty:
            logger.info(f"AKShare 行情: {code} {len(df)} 条")
        return df
    except Exception as e:
        logger.error(f"AKShare 获取行情失败 {code}: {e}")
        return None
