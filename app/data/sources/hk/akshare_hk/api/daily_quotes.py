"""
AKShare HK 港股日线行情 API — stock_hk_daily 接口封装。
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


async def fetch_daily_quotes(
    symbol: str,
    start_date: str,
    end_date: str,
) -> Optional[pd.DataFrame]:
    """获取港股日线行情（前复权）。

    AKShare stock_hk_daily() 返回全部历史数据，需要按日期范围过滤。

    Raises
    ------
    NetworkError
        网络/超时异常（可重试）。
    DataFormatError
        AKShare 返回结构异常（不可重试）。
    DataNotFoundError
        返回空数据（不可重试）。
    DataSourceUnavailableError
        其他未知异常。

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
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        # 网络异常：可重试
        raise map_network_exception(exc, "akshare_hk", _DOMAIN)
    except (KeyError, IndexError, AttributeError, ValueError) as exc:
        # 数据格式异常：AKShare 返回结构不符合预期，不可重试
        raise DataFormatError("akshare_hk", _DOMAIN, f"{symbol}: {exc}")
    except Exception as exc:
        # 其他未知异常
        raise DataSourceUnavailableError("akshare_hk", _DOMAIN, f"{symbol}: {exc}")

    # 空结果：业务正确但无数据，不可重试
    if is_empty_result(df):
        logger.warning(f"akshare_hk 返回空行情: {symbol}")
        raise DataNotFoundError("akshare_hk", _DOMAIN, f"{symbol} 无行情数据")

    # 日期过滤（保留原有业务逻辑）
    date_col = "日期" if "日期" in df.columns else "date"
    if date_col in df.columns:
        df[date_col] = pd.to_datetime(df[date_col])
        start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)
        df = df[(df[date_col] >= start) & (df[date_col] <= end)]
        if df.empty:
            logger.warning(
                f"akshare_hk 日期过滤后无数据: {symbol} {start_date}~{end_date}"
            )
            raise DataNotFoundError(
                "akshare_hk",
                _DOMAIN,
                f"{symbol} 日期范围 {start_date}~{end_date} 无数据",
            )

    logger.info(f"akshare_hk 获取行情: {symbol} {len(df)} 条")
    return df
