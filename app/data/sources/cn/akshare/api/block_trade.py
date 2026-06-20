"""AKShare 大宗交易 API"""
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

_DOMAIN = "block_trade"


async def fetch_block_trade(
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """获取大宗交易数据。

    Args:
        start_date: 开始日期 YYYYMMDD
        end_date: 结束日期 YYYYMMDD

    Raises:
        NetworkError: 网络/超时异常（可重试）
        DataFormatError: AKShare 返回结构异常（不可重试）
        DataNotFoundError: 返回空数据（不可重试）
        DataSourceUnavailableError: 其他未知异常
    """
    try:
        import akshare as ak

        def _fetch():
            from app.data.sources.cn.akshare.api.anti_scraping import wait_rate_limit
            wait_rate_limit()
            return ak.stock_dzjy_mrmx(symbol="A股", start_date=start_date, end_date=end_date)

        df = await asyncio.to_thread(_fetch)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        # 网络异常：可重试
        raise map_network_exception(exc, "akshare", _DOMAIN)
    except (KeyError, IndexError, AttributeError, ValueError) as exc:
        # 数据格式异常：AKShare 返回结构不符合预期，不可重试
        raise DataFormatError(
            "akshare", _DOMAIN,
            f"start_date={start_date}, end_date={end_date}: {exc}",
        )
    except Exception as exc:
        # 其他未知异常
        raise DataSourceUnavailableError(
            "akshare", _DOMAIN,
            f"start_date={start_date}, end_date={end_date}: {exc}",
        )

    # 空结果：业务正确但无数据，不可重试
    if is_empty_result(df):
        logger.warning(
            f"AKShare 大宗交易返回空: start_date={start_date}, end_date={end_date}"
        )
        raise DataNotFoundError(
            "akshare", _DOMAIN,
            f"start_date={start_date}, end_date={end_date} 无大宗交易数据",
        )

    logger.info(f"AKShare 大宗交易: {start_date}-{end_date} {len(df)} 条")
    return df
