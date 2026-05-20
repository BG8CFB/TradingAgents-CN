"""
Tushare 每日指标 API（PE/PB/市值/换手率等）
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

from .connection import TushareConnection

logger = logging.getLogger(__name__)

_DAILY_BASIC_FIELDS = (
    "ts_code,total_mv,circ_mv,pe,pb,turnover_rate,volume_ratio,pe_ttm,pb_mrq,ps,ps_ttm"
)


async def fetch_daily_indicators(
    conn: TushareConnection, trade_date: str
) -> Optional[pd.DataFrame]:
    """获取全市场每日指标"""
    if not conn.is_available():
        return None
    try:
        date_str = trade_date.replace("-", "")
        df = await asyncio.to_thread(
            conn.api.daily_basic,
            trade_date=date_str,
            fields=_DAILY_BASIC_FIELDS,
        )
        if df is not None and not df.empty:
            logger.info(f"Tushare 每日指标: {trade_date} {len(df)} 条")
        return df
    except Exception as e:
        logger.error(f"Tushare 获取每日指标失败 trade_date={trade_date}: {e}")
        return None


async def fetch_daily_indicators_by_symbol(
    conn: TushareConnection, ts_code: str, start_date: str = None, end_date: str = None
) -> Optional[pd.DataFrame]:
    """获取单只股票每日指标"""
    if not conn.is_available():
        return None
    try:
        params = {"ts_code": ts_code, "fields": _DAILY_BASIC_FIELDS}
        if start_date:
            params["start_date"] = start_date.replace("-", "")
        if end_date:
            params["end_date"] = end_date.replace("-", "")
        df = await asyncio.to_thread(conn.api.daily_basic, **params)
        if df is not None and not df.empty:
            logger.info(f"Tushare 每日指标: {ts_code} {len(df)} 条")
        return df
    except Exception as e:
        logger.error(f"Tushare 获取每日指标失败 ts_code={ts_code}: {e}")
        return None
