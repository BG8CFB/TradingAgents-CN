"""
AKShare HK 港股公司行为 API — stock_hk_ggcgy_em 接口封装。
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


async def fetch_corporate_actions(symbol: str) -> Optional[pd.DataFrame]:
    """获取港股公司行为（分红 / 拆股 / 合股 / 供股等）。

    AKShare stock_hk_ggcgy_em() 返回指定股票的历史公司行为记录。

    Parameters
    ----------
    symbol : str
        5 位港股代码，如 "00700"。也可以接受 "0700.HK" 格式（自动清理）。

    Returns
    -------
    Optional[pd.DataFrame]
        原始 DataFrame，包含 代码 / 类型 / 除净日 / 派息 / 送股比例 等字段。
    """
    try:
        import akshare as ak
        # 标准化代码为 5 位
        normalized = str(symbol).replace(".HK", "").lstrip("0").zfill(5)
        df = await asyncio.to_thread(ak.stock_hk_ggcgy_em, symbol=normalized)
        if df is not None and not df.empty:
            logger.info(f"AKShare HK 公司行为: {symbol} {len(df)} 条")
        return df
    except Exception as e:
        logger.debug(f"AKShare HK 获取公司行为失败: {symbol} - {e}")
        return None
