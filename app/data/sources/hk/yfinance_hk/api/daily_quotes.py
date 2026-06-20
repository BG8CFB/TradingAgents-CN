"""
yfinance HK 港股日线行情 API — Ticker.history() 接口封装。
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
from app.data.sources.base.mappers import is_empty_result, map_network_exception

logger = logging.getLogger(__name__)

_DOMAIN = "daily_quotes"


def _to_yfinance_symbol(symbol: str) -> str:
    """港股代码转 yfinance 格式: 00700 / 0700.HK → 0700.HK"""
    code = str(symbol).replace(".HK", "").lstrip("0").zfill(4)
    return f"{code}.HK"


async def fetch_daily_quotes(
    symbol: str,
    start_date: str,
    end_date: str,
) -> Optional[pd.DataFrame]:
    """获取港股日线行情。

    yfinance history() 返回 OHLCV 数据，索引为 DatetimeIndex。

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
        原始 DataFrame，索引为日期，包含 Open / High / Low / Close / Volume 等字段。
    """
    try:
        import yfinance as yf

        hk_symbol = _to_yfinance_symbol(symbol)
        # yfinance end_date 是 exclusive，需 +1 天
        end = pd.to_datetime(end_date) + pd.DateOffset(days=1)
        end_str = end.strftime("%Y-%m-%d")

        def _fetch():
            ticker = yf.Ticker(hk_symbol)
            return ticker.history(start=start_date, end=end_str)

        df = await asyncio.to_thread(_fetch)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        # 网络异常：可重试
        raise map_network_exception(exc, "yfinance_hk", _DOMAIN)
    except (KeyError, IndexError, AttributeError, ValueError) as exc:
        # 数据格式异常：yfinance 返回结构不符合预期，不可重试
        raise DataFormatError("yfinance_hk", _DOMAIN, f"{symbol}: {exc}")
    except Exception as exc:
        # 其他未知异常
        raise DataSourceUnavailableError("yfinance_hk", _DOMAIN, f"{symbol}: {exc}")

    # 空结果：业务正确但无数据，不可重试
    if is_empty_result(df):
        logger.warning(f"yfinance_hk 返回空行情: {symbol}")
        raise DataNotFoundError("yfinance_hk", _DOMAIN, f"{symbol} 无行情数据")

    logger.info(f"yfinance_hk 获取行情: {symbol} {len(df)} 条")
    return df
