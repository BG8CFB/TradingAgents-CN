"""
AKShare 日线行情 API
"""
import asyncio
import logging

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
    code: str,
    start_date: str,
    end_date: str,
    period: str = "daily",
    adjust: str = "qfq",
) -> pd.DataFrame:
    """获取 A 股历史行情

    Raises:
        NetworkError: 网络/超时异常（可重试）
        DataFormatError: AKShare 返回结构异常（不可重试）
        DataNotFoundError: 返回空数据（不可重试）
        DataSourceUnavailableError: 其他未知异常
    """
    try:
        import akshare as ak

        period_map = {"daily": "daily", "weekly": "weekly", "monthly": "monthly"}
        ak_period = period_map.get(period, "daily")

        def _fetch():
            from app.data.sources.cn.akshare.api.anti_scraping import wait_rate_limit
            wait_rate_limit()
            return ak.stock_zh_a_hist(
                symbol=code, period=ak_period,
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
                adjust=adjust,
            )

        df = await asyncio.to_thread(_fetch)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        # 网络异常：可重试
        raise map_network_exception(exc, "akshare", _DOMAIN)
    except (KeyError, IndexError, AttributeError, ValueError) as exc:
        # 数据格式异常：AKShare 返回结构不符合预期，不可重试
        raise DataFormatError("akshare", _DOMAIN, f"code={code}: {exc}")
    except Exception as exc:
        # 其他未知异常
        raise DataSourceUnavailableError("akshare", _DOMAIN, f"code={code}: {exc}")

    # 空结果：业务正确但无数据，不可重试
    if is_empty_result(df):
        logger.warning(f"AKShare 行情返回空: code={code}")
        raise DataNotFoundError("akshare", _DOMAIN, f"code={code} 无行情数据")

    logger.info(f"AKShare 行情: {code} {len(df)} 条")
    return df
