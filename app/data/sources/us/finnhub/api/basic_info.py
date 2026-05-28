"""
Finnhub US 美股基础信息 API（股票列表）
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

from app.utils.ds_key_utils import get_datasource_api_key

logger = logging.getLogger(__name__)


async def fetch_stock_list() -> Optional[pd.DataFrame]:
    """获取美股股票列表。

    通过 finnhub.Client.stock_symbols(exchange="US") 获取全市场股票列表。

    Returns:
        股票列表 DataFrame，失败返回 None
    """
    api_key = get_datasource_api_key("finnhub")
    if not api_key:
        logger.debug("Finnhub API Key 未配置")
        return None
    try:
        import finnhub

        def _fetch():
            client = finnhub.Client(api_key=api_key)
            symbols = client.stock_symbols(exchange="US")
            return pd.DataFrame(symbols) if symbols else None

        df = await asyncio.to_thread(_fetch)
        if df is not None and not df.empty:
            logger.info(f"Finnhub-US 股票列表: {len(df)} 只")
        return df
    except Exception as e:
        logger.error(f"Finnhub-US 获取股票列表失败: {e}")
        return None
