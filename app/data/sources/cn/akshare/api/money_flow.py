"""AKShare 资金流向 API"""
import asyncio
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


async def fetch_money_flow_by_symbol(
    symbol: str,
) -> Optional[pd.DataFrame]:
    """获取个股资金流向。

    Args:
        symbol: 6位股票代码（不带后缀）
    """
    try:
        import akshare as ak

        def _fetch():
            return ak.stock_individual_fund_flow(stock=symbol, market="sh" if symbol.startswith("6") else "sz")

        df = await asyncio.to_thread(_fetch)
        if df is not None and not df.empty:
            logger.info(f"AKShare 资金流向: {symbol} {len(df)} 条")
        return df
    except Exception as e:
        logger.error(f"AKShare 获取资金流向失败 {symbol}: {e}")
        return None
