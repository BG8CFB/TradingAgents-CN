"""
AKShare HK 港股公告/新闻 API — stock_hk_notice_report 接口封装。
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


async def fetch_news(symbol: str) -> Optional[pd.DataFrame]:
    """获取港股公告/报告信息。

    AKShare stock_hk_notice_report() 返回指定股票的公告列表。

    Parameters
    ----------
    symbol : str
        5 位港股代码，如 "00700"。也可以接受 "0700.HK" 格式（自动清理）。

    Returns
    -------
    Optional[pd.DataFrame]
        原始 DataFrame，包含 股票代码 / 标题 / 公告日期 / 内容 / 链接 等字段。
    """
    try:
        import akshare as ak
        # 标准化代码为 5 位
        normalized = str(symbol).replace(".HK", "").lstrip("0").zfill(5)
        df = await asyncio.to_thread(ak.stock_hk_notice_report, symbol=normalized)
        if df is not None and not df.empty:
            logger.info(f"AKShare HK 公告: {symbol} {len(df)} 条")
        return df
    except Exception as e:
        logger.debug(f"AKShare HK 获取公告失败: {symbol} - {e}")
        return None
