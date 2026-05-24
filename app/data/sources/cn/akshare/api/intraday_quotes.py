"""AKShare 分钟级行情 API"""
import asyncio
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


async def fetch_intraday_quotes(
    code: str,
    period: str = "30",
) -> Optional[pd.DataFrame]:
    """获取 A 股分钟级行情。

    Args:
        code: 6位股票代码（不带后缀）
        period: 频率 "1"/"5"/"15"/"30"/"60"
    """
    try:
        import akshare as ak

        def _fetch():
            return ak.stock_zh_a_hist_min_em(symbol=code, period=period, adjust="")

        df = await asyncio.to_thread(_fetch)
        if df is not None and not df.empty:
            logger.info(f"AKShare 分钟线: {code} freq={period} {len(df)} 条")
        return df
    except Exception as e:
        logger.error(f"AKShare 获取分钟线失败 {code}: {e}")
        return None
