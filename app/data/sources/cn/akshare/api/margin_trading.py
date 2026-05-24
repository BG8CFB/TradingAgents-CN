"""AKShare 融资融券 API"""
import asyncio
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


async def fetch_margin_trading(
    symbol: str,
) -> Optional[pd.DataFrame]:
    """获取个股融资融券数据。

    Args:
        symbol: 6位股票代码（不带后缀）
    """
    try:
        import akshare as ak

        def _fetch():
            code = symbol.zfill(6)
            if code.startswith("6"):
                return ak.stock_margin_detail_sse(code=code)
            elif code.startswith("0") or code.startswith("3"):
                return ak.stock_margin_underlying_info_szse(date="")
            else:
                return None

        df = await asyncio.to_thread(_fetch)
        if df is not None and not df.empty:
            if symbol.startswith("0") or symbol.startswith("3"):
                col = "证券代码" if "证券代码" in df.columns else "代码"
                df = df[df[col].astype(str).str.zfill(6) == symbol.zfill(6)]
            logger.info(f"AKShare 融资融券: {symbol} {len(df)} 条")
        return df
    except Exception as e:
        logger.error(f"AKShare 获取融资融券失败 {symbol}: {e}")
        return None
