"""
Tushare HK 港股财务指标 API — hk_fina_indicator 接口封装。
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


async def fetch_fina_indicator(
    api,
    ts_code: str,
) -> Optional[pd.DataFrame]:
    """获取港股财务指标（ROE / EPS / BPS 等）。

    Parameters
    ----------
    api : tushare.pro_api
        已初始化的 Tushare pro_api 实例。
    ts_code : str
        Tushare 格式港股代码，如 "0700.HK"。

    Returns
    -------
    Optional[pd.DataFrame]
        原始 DataFrame，包含 ts_code / end_date / roe / eps / bps 等字段。
    """
    if api is None:
        return None
    try:
        df = await asyncio.to_thread(lambda: api.hk_fina_indicator(ts_code=ts_code))
        if df is not None and not df.empty:
            logger.info(f"Tushare HK 财务指标: {ts_code} {len(df)} 条")
        return df
    except Exception as e:
        logger.error(f"Tushare HK 获取财务指标失败: {ts_code} - {e}")
        return None
