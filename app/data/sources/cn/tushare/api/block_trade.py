"""
Tushare 大宗交易 API

接口: block_trade (大宗交易明细)
要求: >= 120 积分
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

from .connection import TushareConnection

logger = logging.getLogger(__name__)


async def fetch_block_trade(
    conn: TushareConnection,
    ts_code: str = None,
    start_date: str = None,
    end_date: str = None,
    limit: int = 500,
) -> Optional[pd.DataFrame]:
    """获取大宗交易数据"""
    if not conn.is_available():
        return None

    kwargs = {}
    if ts_code:
        kwargs["ts_code"] = ts_code
    if start_date:
        kwargs["start_date"] = str(start_date).replace("-", "")
    if end_date:
        kwargs["end_date"] = str(end_date).replace("-", "")
    if not start_date and not end_date and not ts_code:
        kwargs["limit"] = limit

    try:
        df = await asyncio.to_thread(conn.api.block_trade, **kwargs)
        if df is None or df.empty:
            logger.debug(f"Tushare 大宗交易为空")
            return None
        logger.info(f"Tushare 大宗交易: {len(df)} 条")
        return df
    except Exception as e:
        logger.error(f"Tushare 大宗交易失败: {e}")
        return None
