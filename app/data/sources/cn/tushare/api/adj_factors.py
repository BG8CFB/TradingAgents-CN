"""
Tushare 复权因子 API
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

from .connection import TushareConnection

logger = logging.getLogger(__name__)


async def fetch_adj_factors(
    conn: TushareConnection,
    ts_code: str,
    start_date: str = None,
    end_date: str = None,
) -> Optional[pd.DataFrame]:
    """获取复权因子"""
    if not conn.is_available():
        return None
    try:
        params: dict = {"ts_code": ts_code}
        if start_date:
            params["start_date"] = start_date.replace("-", "")
        if end_date:
            params["end_date"] = end_date.replace("-", "")
        df = await asyncio.to_thread(conn.api.adj_factor, **params)
        if df is not None and not df.empty:
            logger.info(f"Tushare 复权因子: {ts_code} {len(df)} 条")
        return df
    except Exception as e:
        logger.error(f"Tushare 获取复权因子失败 ts_code={ts_code}: {e}")
        return None
