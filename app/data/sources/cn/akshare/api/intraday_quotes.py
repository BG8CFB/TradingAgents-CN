"""AKShare 分钟级行情 API"""
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

_DOMAIN = "intraday_quotes"


async def fetch_intraday_quotes(
    code: str,
    period: str = "30",
) -> pd.DataFrame:
    """获取 A 股分钟级行情。

    Args:
        code: 6位股票代码（不带后缀）
        period: 频率 "1"/"5"/"15"/"30"/"60"

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
            return ak.stock_zh_a_hist_min_em(symbol=code, period=period, adjust="")

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
        logger.warning(f"AKShare 分钟线返回空: code={code}")
        raise DataNotFoundError("akshare", _DOMAIN, f"code={code} 无分钟线数据")

    logger.info(f"AKShare 分钟线: {code} freq={period} {len(df)} 条")
    return df
