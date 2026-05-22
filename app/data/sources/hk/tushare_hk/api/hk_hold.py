"""
Tushare HK 港股南向持股 API — hk_hold 接口封装。
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


def _format_compact(date_str: str) -> str:
    """YYYY-MM-DD -> YYYYMMDD"""
    return str(date_str).replace("-", "") if date_str else ""


async def fetch_southbound_holdings(
    api,
    ts_code: str = None,
    start_date: str = None,
    end_date: str = None,
) -> Optional[pd.DataFrame]:
    """获取港股通南向持股数据。

    Parameters
    ----------
    api : tushare.pro_api
        已初始化的 Tushare pro_api 实例。
    ts_code : str, optional
        Tushare 格式港股代码，如 "0700.HK"。不传则返回全市场。
    start_date : str, optional
        起始日期，格式 YYYY-MM-DD 或 YYYYMMDD。
    end_date : str, optional
        截止日期，格式 YYYY-MM-DD 或 YYYYMMDD。

    Returns
    -------
    Optional[pd.DataFrame]
        原始 DataFrame，包含 ts_code / trade_date / vol / amount 等字段。
    """
    if api is None:
        return None
    try:
        params: dict = {}
        if ts_code:
            params["ts_code"] = ts_code
        if start_date:
            params["start_date"] = _format_compact(start_date)
        if end_date:
            params["end_date"] = _format_compact(end_date)
        df = await asyncio.to_thread(lambda: api.hk_hold(**params))
        if df is not None and not df.empty:
            logger.info(f"Tushare HK 南向持股: {ts_code or '全市场'} {len(df)} 条")
        return df
    except Exception as e:
        logger.error(f"Tushare HK 获取南向持股失败: {ts_code} - {e}")
        return None
