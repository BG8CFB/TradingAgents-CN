"""
Tushare 龙虎榜 API

接口: top_list (龙虎榜每日明细) + top_inst (龙虎榜机构明细)
要求: >= 120 积分
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

from .connection import TushareConnection

logger = logging.getLogger(__name__)


async def fetch_dragon_tiger(
    conn: TushareConnection,
    trade_date: str = None,
    start_date: str = None,
    end_date: str = None,
    ts_code: str = None,
) -> Optional[pd.DataFrame]:
    """
    获取龙虎榜数据

    支持按日期或按股票代码查询。按股票代码查询时会扫描最近 30 个交易日。
    """
    if not conn.is_available():
        return None

    if ts_code:
        return await _fetch_by_symbol(conn, ts_code)

    return await _fetch_by_date(conn, trade_date, start_date, end_date)


async def _fetch_by_date(
    conn: TushareConnection,
    trade_date: str = None,
    start_date: str = None,
    end_date: str = None,
) -> Optional[pd.DataFrame]:
    """按日期获取龙虎榜"""
    try:
        kwargs = {}
        if trade_date:
            kwargs["trade_date"] = str(trade_date).replace("-", "")
        elif start_date:
            kwargs["start_date"] = str(start_date).replace("-", "")
            kwargs["end_date"] = str(end_date or start_date).replace("-", "")

        df = await asyncio.to_thread(conn.api.top_list, **kwargs)
        if df is None or df.empty:
            return None
        logger.info(f"Tushare 龙虎榜(日期): {len(df)} 条")
        return df
    except Exception as e:
        logger.error(f"Tushare 龙虎榜(日期)失败: {e}")
        return None


async def _fetch_by_symbol(
    conn: TushareConnection,
    ts_code: str,
) -> Optional[pd.DataFrame]:
    """按股票代码扫描最近龙虎榜记录"""
    from datetime import datetime, timedelta

    symbol = ts_code.split(".")[0] if "." in ts_code else ts_code

    for days_back in range(0, 30):
        check_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")
        try:
            df = await asyncio.to_thread(
                conn.api.top_list, trade_date=check_date
            )
            if df is not None and not df.empty:
                filtered = df[df["ts_code"].str.startswith(symbol)]
                if not filtered.empty:
                    logger.info(
                        f"Tushare 龙虎榜({ts_code}): {len(filtered)} 条 ({check_date})"
                    )
                    return filtered
        except Exception:
            continue

    logger.debug(f"Tushare 龙虎榜: {ts_code} 近 30 天无记录")
    return None
