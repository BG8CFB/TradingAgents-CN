"""
Tushare HK 港股基础信息 API — hk_basic 接口封装。
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


async def fetch_stock_list(api) -> Optional[pd.DataFrame]:
    """获取港股全部股票列表。

    Parameters
    ----------
    api : tushare.pro_api
        已初始化的 Tushare pro_api 实例（使用 TUSHARE_HK_TOKEN）。

    Returns
    -------
    Optional[pd.DataFrame]
        原始 DataFrame，包含 ts_code / name / industry 等字段。
    """
    if api is None:
        return None
    try:
        df = await asyncio.to_thread(lambda: api.hk_basic())
        if df is not None and not df.empty:
            logger.info(f"Tushare HK 获取股票列表: {len(df)} 只")
        return df
    except Exception as e:
        logger.error(f"Tushare HK 获取股票列表失败: {e}")
        return None
