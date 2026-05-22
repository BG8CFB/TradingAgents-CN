"""
Tushare HK 港股每日指标（日线复权数据）API — hk_daily_adj 接口封装。
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


def _format_compact(date_str: str) -> str:
    """YYYY-MM-DD -> YYYYMMDD"""
    return str(date_str).replace("-", "") if date_str else ""


async def fetch_daily_adj(
    api,
    ts_code: str,
    start_date: str,
    end_date: str,
) -> Optional[pd.DataFrame]:
    """获取港股日线复权指标数据。

    Tushare HK 的 hk_daily_adj 接口返回 PE / PB / 市值 / 换手率等指标。

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
        原始 DataFrame，包含 ts_code / trade_date / pe / pb / total_mv / circ_mv 等。
    """
    if api is None:
        return None
    try:
        start_str = _format_compact(start_date)
        end_str = _format_compact(end_date)
        df = await asyncio.to_thread(
            lambda: api.hk_daily_adj(
                ts_code=ts_code,
                start_date=start_str,
                end_date=end_str,
            )
        )
        if df is not None and not df.empty:
            logger.info(f"Tushare HK 每日指标: {ts_code} {len(df)} 条")
        return df
    except Exception as e:
        logger.error(f"Tushare HK 获取每日指标失败: {ts_code} - {e}")
        return None
