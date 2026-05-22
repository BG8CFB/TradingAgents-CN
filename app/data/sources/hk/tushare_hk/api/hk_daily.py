"""
Tushare HK 港股日线行情 API — hk_daily 接口封装。
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


def _format_compact(date_str: str) -> str:
    """YYYY-MM-DD -> YYYYMMDD"""
    return str(date_str).replace("-", "") if date_str else ""


async def fetch_daily_quotes(
    api,
    ts_code: str,
    start_date: str,
    end_date: str,
) -> Optional[pd.DataFrame]:
    """获取港股日线行情（未复权）。

    Parameters
    ----------
    api : tushare.pro_api
        已初始化的 Tushare pro_api 实例。
    ts_code : str
        Tushare 格式港股代码，如 "0700.HK"。
    start_date : str
        起始日期，格式 YYYY-MM-DD 或 YYYYMMDD。
    end_date : str
        截止日期，格式 YYYY-MM-DD 或 YYYYMMDD。

    Returns
    -------
    Optional[pd.DataFrame]
        原始 DataFrame，包含 ts_code / trade_date / open / high / low / close / vol 等。
    """
    if api is None:
        return None
    try:
        start_str = _format_compact(start_date)
        end_str = _format_compact(end_date)
        df = await asyncio.to_thread(
            lambda: api.hk_daily(
                ts_code=ts_code,
                start_date=start_str,
                end_date=end_str,
            )
        )
        if df is None or df.empty:
            logger.warning(f"Tushare HK 返回空行情: {ts_code} {start_str}-{end_str}")
            return None
        logger.info(f"Tushare HK 获取行情: {ts_code} {len(df)} 条")
        return df
    except Exception as e:
        logger.error(f"Tushare HK 获取行情失败: {ts_code} - {e}")
        return None
