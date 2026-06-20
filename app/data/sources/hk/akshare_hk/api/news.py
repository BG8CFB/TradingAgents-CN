"""
AKShare HK 港股公告/新闻 API — stock_hk_notice_report 接口封装。
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

_DOMAIN = "news"


async def fetch_news(symbol: str) -> Optional[pd.DataFrame]:
    """获取港股公告/报告信息。

    AKShare stock_hk_notice_report() 返回指定股票的公告列表。

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
        logger.warning(f"akshare_hk 公告返回空: {symbol}")
        raise DataNotFoundError("akshare_hk", _DOMAIN, f"{symbol} 无公告数据")

    logger.info(f"akshare_hk 公告: {symbol} {len(df)} 条")
    return df
