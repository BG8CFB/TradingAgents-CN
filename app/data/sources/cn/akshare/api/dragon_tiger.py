"""AKShare 龙虎榜 API"""
import asyncio
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


async def fetch_dragon_tiger(
    start_date: str,
    end_date: str,
) -> Optional[pd.DataFrame]:
    """获取龙虎榜数据。

    Args:
        start_date: 开始日期 YYYYMMDD
        end_date: 结束日期 YYYYMMDD
    """
    try:
        import akshare as ak

        def _fetch():
            from app.data.sources.cn.akshare.api.anti_scraping import wait_rate_limit
            wait_rate_limit()
            return ak.stock_lhb_detail_em(start_date=start_date, end_date=end_date)

        df = await asyncio.to_thread(_fetch)
        if df is not None and not df.empty:
            logger.info(f"AKShare 龙虎榜: {start_date}-{end_date} {len(df)} 条")
        return df
    except Exception as e:
        logger.error(f"AKShare 获取龙虎榜失败: {e}")
        return None
