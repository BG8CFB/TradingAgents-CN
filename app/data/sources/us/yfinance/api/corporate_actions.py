"""
yfinance US 美股公司行为 API（分红/拆股）
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

from app.data.sources.base.exceptions import (
    DataNotFoundError,
    DataSourceUnavailableError,
)
from app.data.sources.base.mappers import (
    map_network_exception,
)

logger = logging.getLogger(__name__)

_DOMAIN = "corporate_actions"


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

    Raises:
        NetworkError: 网络/超时异常（可重试）
        DataFormatError: yfinance 返回结构异常（不可重试）
        DataNotFoundError: 返回空数据（不可重试）
        DataSourceUnavailableError: 其他未知异常
    """
    try:
        import yfinance as yf

        ticker = symbol.upper().strip()

        def _fetch():
            t = yf.Ticker(ticker)
            return {"dividends": t.dividends, "splits": t.splits}

        result = await asyncio.to_thread(_fetch)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "yfinance", _DOMAIN)
    except (KeyError, IndexError, ValueError, AttributeError) as exc:
        from app.data.sources.base.exceptions import DataFormatError
        raise DataFormatError("yfinance", _DOMAIN, f"symbol={symbol}: {exc}")
    except Exception as exc:
        raise DataSourceUnavailableError("yfinance", _DOMAIN, f"symbol={symbol}: {exc}")

    # 业务逻辑：解析 + 日期过滤
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
        logger.warning(f"yfinance 返回空数据: {symbol} 公司行为")
        raise DataNotFoundError("yfinance", _DOMAIN, f"{symbol} 无公司行为数据")

    df = pd.DataFrame(records)
    logger.info(f"yfinance 获取成功: {symbol} {len(df)} 条")
    return df
