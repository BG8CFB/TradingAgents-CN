"""
Tushare 股票基础信息 API
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from .connection import TushareConnection

logger = logging.getLogger(__name__)

_STOCK_BASIC_FIELDS = (
    "ts_code,symbol,name,area,industry,market,exchange,list_date,is_hs"
)


async def fetch_stock_list(conn: TushareConnection, market: str = None) -> Optional[pd.DataFrame]:
    """获取 A 股股票列表"""
    if not conn.is_available():
        return None
    try:
        params: Dict[str, Any] = {"list_status": "L", "fields": _STOCK_BASIC_FIELDS}
        if market == "CN":
            params["exchange"] = "SSE,SZSE"
        df = await asyncio.to_thread(conn.api.stock_basic, **params)
        if df is not None and not df.empty:
            logger.info(f"Tushare 获取股票列表: {len(df)} 只")
        return df
    except Exception as e:
        logger.error(f"Tushare 获取股票列表失败: {e}")
        return None


async def fetch_stock_basic_info(
    conn: TushareConnection, ts_code: str
) -> Optional[pd.DataFrame]:
    """获取单只股票基础信息"""
    if not conn.is_available():
        return None
    try:
        if ts_code.endswith(".HK"):
            df = await asyncio.to_thread(conn.api.hk_basic, ts_code=ts_code)
        else:
            df = await asyncio.to_thread(
                conn.api.stock_basic,
                ts_code=ts_code,
                fields=_STOCK_BASIC_FIELDS + ",act_name,act_ent_type",
            )
        return df
    except Exception as e:
        logger.error(f"Tushare 获取基础信息失败 ts_code={ts_code}: {e}")
        return None
