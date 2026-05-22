"""
yfinance HK 港股公司行为 API — Ticker.dividends + Ticker.splits 接口封装。
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


def _to_yfinance_symbol(symbol: str) -> str:
    """港股代码转 yfinance 格式: 00700 / 0700.HK → 0700.HK"""
    code = str(symbol).replace(".HK", "").lstrip("0").zfill(4)
    return f"{code}.HK"


async def fetch_corporate_actions(
    symbol: str,
    start_date: str,
    end_date: str,
) -> Optional[pd.DataFrame]:
    """获取港股公司行为（分红 + 拆股）。

    分别获取 Ticker.dividends 和 Ticker.splits，
    按日期范围过滤后合并为 DataFrame。

    Parameters
    ----------
    symbol : str
        港股代码，支持 "00700" / "0700.HK" 等格式。
    start_date : str
        起始日期，格式 YYYY-MM-DD。
    end_date : str
        截止日期，格式 YYYY-MM-DD。

    Returns
    -------
    Optional[pd.DataFrame]
        原始 DataFrame，每行包含 date / action_type / amount 或 ratio / symbol。
    """
    try:
        import yfinance as yf
        hk_symbol = _to_yfinance_symbol(symbol)

        def _fetch():
            ticker = yf.Ticker(hk_symbol)
            return {
                "dividends": ticker.dividends,
                "splits": ticker.splits,
            }

        result = await asyncio.to_thread(_fetch)
        if not result:
            return None

        records = []

        # 分红记录
        dividends = result.get("dividends")
        if dividends is not None and not dividends.empty:
            for date, val in dividends.items():
                date_str = str(date)[:10]
                if start_date <= date_str <= end_date:
                    records.append({
                        "date": date,
                        "action_type": "cash_dividend",
                        "amount": float(val),
                        "symbol": symbol,
                    })

        # 拆股记录
        splits = result.get("splits")
        if splits is not None and not splits.empty:
            for date, val in splits.items():
                date_str = str(date)[:10]
                if start_date <= date_str <= end_date:
                    records.append({
                        "date": date,
                        "action_type": "stock_split",
                        "ratio": float(val),
                        "symbol": symbol,
                    })

        if not records:
            logger.debug(f"yfinance HK 无公司行为: {symbol} {start_date}~{end_date}")
            return None

        logger.info(f"yfinance HK 公司行为: {symbol} {len(records)} 条")
        return pd.DataFrame(records)
    except Exception as e:
        logger.debug(f"yfinance HK 获取公司行为失败: {symbol} - {e}")
        return None
