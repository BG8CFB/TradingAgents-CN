"""
Tushare HK 港股实时行情 API — rt_hk_k 接口封装。
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


async def fetch_realtime_quotes(api) -> Optional[pd.DataFrame]:
    """获取港股全市场实时行情快照。

    Parameters
    ----------
    api : tushare.pro_api
        已初始化的 Tushare pro_api 实例。

    Returns
    -------
    Optional[pd.DataFrame]
        原始 DataFrame，包含 ts_code / price / volume / amount 等字段。
    """
    if api is None:
        return None
    try:
        df = await asyncio.to_thread(lambda: api.rt_hk_k())
        if df is not None and not df.empty:
            logger.info(f"Tushare HK 实时行情: {len(df)} 只")
        return df
    except Exception as e:
        logger.error(f"Tushare HK 获取实时行情失败: {e}")
        return None
