"""
AKShare HK 港股日线行情 API — stock_hk_daily 接口封装。
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


async def fetch_daily_quotes(
    symbol: str,
    start_date: str,
    end_date: str,
) -> Optional[pd.DataFrame]:
    """获取港股日线行情（前复权）。

    AKShare stock_hk_daily() 返回全部历史数据，需要按日期范围过滤。

    Parameters
    ----------
    symbol : str
        5 位港股代码，如 "00700"。也可以接受 "0700.HK" 格式（自动清理）。
    start_date : str
        起始日期，格式 YYYY-MM-DD。
    end_date : str
        截止日期，格式 YYYY-MM-DD。

    Returns
    -------
    Optional[pd.DataFrame]
        原始 DataFrame（已按日期范围过滤），包含 日期 / 开盘 / 收盘 / 最高 / 最低 等中文列名。
    """
    try:
        import akshare as ak
        # 标准化代码为 5 位
        normalized = str(symbol).replace(".HK", "").lstrip("0").zfill(5)
        df = await asyncio.to_thread(ak.stock_hk_daily, symbol=normalized, adjust="qfq")
        if df is None or df.empty:
            logger.warning(f"AKShare HK 返回空行情: {symbol}")
            return None

        # 日期过滤
        date_col = "日期" if "日期" in df.columns else "date"
        if date_col in df.columns:
            df[date_col] = pd.to_datetime(df[date_col])
            start = pd.to_datetime(start_date)
            end = pd.to_datetime(end_date)
            df = df[(df[date_col] >= start) & (df[date_col] <= end)]
            if df.empty:
                logger.warning(f"AKShare HK 日期过滤后无数据: {symbol} {start_date}~{end_date}")
                return None

        logger.info(f"AKShare HK 获取行情: {symbol} {len(df)} 条")
        return df
    except Exception as e:
        logger.error(f"AKShare HK 获取行情失败: {symbol} - {e}")
        return None
