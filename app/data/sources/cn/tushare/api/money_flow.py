"""
Tushare 资金流向 API

接口: moneyflow (个股资金流向)
要求: >= 120 积分
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

from .connection import TushareConnection

logger = logging.getLogger(__name__)


async def fetch_money_flow(
    conn: TushareConnection,
    ts_code: str,
    start_date: str = None,
    end_date: str = None,
    limit: int = 60,
) -> Optional[pd.DataFrame]:
    """获取个股资金流向"""
    if not conn.is_available():
        return None

    kwargs = {"ts_code": ts_code}
    if start_date:
        kwargs["start_date"] = str(start_date).replace("-", "")
    if end_date:
        kwargs["end_date"] = str(end_date).replace("-", "")
    if not start_date and not end_date:
        kwargs["limit"] = limit

    try:
        df = await asyncio.to_thread(conn.api.moneyflow, **kwargs)
        if df is None or df.empty:
            logger.debug(f"Tushare 资金流向为空: {ts_code}")
            return None
        logger.info(f"Tushare 资金流向: {ts_code} {len(df)} 条")
        return df
    except Exception as e:
        logger.error(f"Tushare 资金流向失败 {ts_code}: {e}")
        return None
