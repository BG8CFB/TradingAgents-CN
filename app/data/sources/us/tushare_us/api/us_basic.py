"""
Tushare US 美股基础信息 API
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


async def fetch_stock_list(api) -> Optional[pd.DataFrame]:
    """获取美股股票列表（主要美股 + 中概股）。

    Args:
        api: tushare pro_api 实例

    Returns:
        包含美股基础信息的 DataFrame，失败返回 None
    """
    if api is None:
        return None
    try:
        df = await asyncio.to_thread(api.us_basic)
        if df is not None and not df.empty:
            logger.info(f"Tushare US 获取股票列表: {len(df)} 只")
        return df
    except Exception as e:
        logger.error(f"Tushare US 获取股票列表失败: {e}")
        return None
