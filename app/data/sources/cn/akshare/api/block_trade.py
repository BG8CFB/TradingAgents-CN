"""AKShare 大宗交易 API"""
import asyncio
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


async def fetch_block_trade(
    start_date: str,
    end_date: str,
) -> Optional[pd.DataFrame]:
    """获取大宗交易数据。

    Args:
        start_date: 开始日期 YYYYMMDD
        end_date: 结束日期 YYYYMMDD
    """
    try:
        import akshare as ak

        def _fetch():
            return ak.stock_dzjy_mrmx(symbol="A股", start_date=start_date, end_date=end_date)

        df = await asyncio.to_thread(_fetch)
        if df is not None and not df.empty:
            logger.info(f"AKShare 大宗交易: {start_date}-{end_date} {len(df)} 条")
        return df
    except Exception as e:
        logger.error(f"AKShare 获取大宗交易失败: {e}")
        return None
