"""
AKShare HK 港股基础信息 API — stock_hk_spot_em 接口封装。
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


async def fetch_stock_list() -> Optional[pd.DataFrame]:
    """获取港股全市场实时行情快照（东方财富数据源）。

    AKShare 的 stock_hk_spot_em() 返回所有港股的实时快照数据，
    包含 代码 / 名称 / 最新价 / 涨跌幅 / 成交量 等。

    Returns
    -------
    Optional[pd.DataFrame]
        原始 DataFrame，包含 代码 / 名称 / 最新价 等中文列名。
    """
    try:
        import akshare as ak
        df = await asyncio.to_thread(ak.stock_hk_spot_em)
        if df is not None and not df.empty:
            logger.info(f"AKShare HK 获取股票列表: {len(df)} 只")
        return df
    except Exception as e:
        logger.error(f"AKShare HK 获取股票列表失败: {e}")
        return None
