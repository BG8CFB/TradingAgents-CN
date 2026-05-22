"""
yfinance US 美股公司行为 API（分红/拆股）
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


async def fetch_corporate_actions(
    symbol: str,
    start_date: str,
    end_date: str,
) -> Optional[pd.DataFrame]:
    """获取美股公司行为（分红 + 拆股），合并为单个 DataFrame。

    通过 yf.Ticker(symbol).dividends 和 yf.Ticker(symbol).splits 获取，
    日期范围过滤后合并。

    Args:
        symbol: 股票代码（大写），如 "AAPL"
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)

    Returns:
        公司行为 DataFrame（含 date/action_type/amount 或 ratio/symbol），失败返回 None
    """
    try:
        import yfinance as yf

        ticker = symbol.upper().strip()

        def _fetch():
            t = yf.Ticker(ticker)
            return {"dividends": t.dividends, "splits": t.splits}

        result = await asyncio.to_thread(_fetch)
        records = []

        divs = result.get("dividends")
        if divs is not None and not divs.empty:
            for date, val in divs.items():
                ds = str(date)[:10]
                if start_date <= ds <= end_date:
                    records.append({
                        "date": ds,
                        "action_type": "cash_dividend",
                        "amount": val,
                        "symbol": ticker,
                    })

        splits = result.get("splits")
        if splits is not None and not splits.empty:
            for date, val in splits.items():
                ds = str(date)[:10]
                if start_date <= ds <= end_date:
                    action = "stock_split" if val > 1 else "reverse_split"
                    records.append({
                        "date": ds,
                        "action_type": action,
                        "ratio": val,
                        "symbol": ticker,
                    })

        if not records:
            return None
        df = pd.DataFrame(records)
        logger.info(f"yfinance-US 公司行为: {ticker} {len(df)} 条")
        return df
    except Exception as e:
        logger.debug(f"yfinance-US 获取公司行为失败 {symbol}: {e}")
        return None
