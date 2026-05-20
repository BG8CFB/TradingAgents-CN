"""
AKShare 股票基础信息 API
"""
import asyncio
import logging
import time
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

_stock_list_cache = None
_stock_list_cache_time = 0
_CACHE_TTL = 3600  # 1 小时


async def fetch_stock_list() -> Optional[pd.DataFrame]:
    """获取 A 股股票列表（带 1 小时内存缓存）"""
    global _stock_list_cache, _stock_list_cache_time

    if _stock_list_cache is not None and (time.time() - _stock_list_cache_time) < _CACHE_TTL:
        return _stock_list_cache

    try:
        import akshare as ak

        def _fetch():
            return ak.stock_info_a_code_name()

        df = await asyncio.to_thread(_fetch)
        if df is not None and not df.empty:
            _stock_list_cache = df
            _stock_list_cache_time = time.time()
            logger.info(f"AKShare 获取股票列表: {len(df)} 只")
        return df
    except Exception as e:
        logger.error(f"AKShare 获取股票列表失败: {e}")
        return None


async def fetch_stock_basic_info(code: str) -> Optional[dict]:
    """获取单只股票基础信息"""
    try:
        import akshare as ak

        def _fetch():
            return ak.stock_individual_info_em(symbol=code)

        df = await asyncio.to_thread(_fetch)
        if df is not None and not df.empty:
            result = {}
            for _, row in df.iterrows():
                result[str(row.iloc[0]).strip()] = row.iloc[1]
            return result
        return None
    except Exception as e:
        logger.error(f"AKShare 获取基础信息失败 {code}: {e}")
        return None
