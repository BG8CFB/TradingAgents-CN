"""
yfinance HK 港股公司行为 API — Ticker.dividends + Ticker.splits 接口封装。
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

from app.data.sources.base.exceptions import (
    DataFormatError,
    DataNotFoundError,
    DataSourceUnavailableError,
)
from app.data.sources.base.mappers import map_network_exception

logger = logging.getLogger(__name__)

_DOMAIN = "corporate_actions"


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

    Raises
    ------
    NetworkError
        网络/超时异常（可重试）。
    DataFormatError
        yfinance 返回结构异常（不可重试）。
    DataNotFoundError
        返回空数据（不可重试）。
    DataSourceUnavailableError
        其他未知异常。

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
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        # 网络异常：可重试
        raise map_network_exception(exc, "yfinance_hk", _DOMAIN)
    except (KeyError, IndexError, AttributeError, ValueError) as exc:
        # 数据格式异常：yfinance 返回结构不符合预期，不可重试
        raise DataFormatError("yfinance_hk", _DOMAIN, f"{symbol}: {exc}")
    except Exception as exc:
        # 其他未知异常
        raise DataSourceUnavailableError("yfinance_hk", _DOMAIN, f"{symbol}: {exc}")

    # 业务逻辑：合并 dividends + splits（保留原实现）
    records = []

    # 分红记录
    dividends = result.get("dividends") if result else None
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
    splits = result.get("splits") if result else None
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

    # 空结果：业务正确但无数据，不可重试
    if not records:
        logger.debug(
            f"yfinance_hk 无公司行为: {symbol} {start_date}~{end_date}"
        )
        raise DataNotFoundError(
            "yfinance_hk",
            _DOMAIN,
            f"{symbol} 日期范围 {start_date}~{end_date} 无公司行为",
        )

    logger.info(f"yfinance_hk 公司行为: {symbol} {len(records)} 条")
    return pd.DataFrame(records)
