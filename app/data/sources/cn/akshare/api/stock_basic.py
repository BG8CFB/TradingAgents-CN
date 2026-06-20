"""
AKShare 股票基础信息 API
"""
import asyncio
import logging
import time

import pandas as pd

from app.data.sources.base.exceptions import (
    DataFormatError,
    DataNotFoundError,
    DataSourceUnavailableError,
)
from app.data.sources.base.mappers import is_empty_result, map_network_exception

logger = logging.getLogger(__name__)

_DOMAIN = "stock_basic"

_stock_list_cache = None
_stock_list_cache_time = 0
_CACHE_TTL = 3600  # 1 小时


async def fetch_stock_list() -> pd.DataFrame:
    """获取 A 股股票列表（带 1 小时内存缓存）。

    Raises:
        NetworkError: 网络/超时异常（可重试）
        DataFormatError: AKShare 返回结构异常（不可重试）
        DataNotFoundError: 返回空数据（不可重试）
        DataSourceUnavailableError: 其他未知异常
    """
    global _stock_list_cache, _stock_list_cache_time

    if _stock_list_cache is not None and (time.time() - _stock_list_cache_time) < _CACHE_TTL:
        return _stock_list_cache

    try:
        import akshare as ak

        def _fetch():
            from app.data.sources.cn.akshare.api.anti_scraping import wait_rate_limit
            wait_rate_limit()
            return ak.stock_info_a_code_name()

        df = await asyncio.to_thread(_fetch)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        # 网络异常：可重试
        raise map_network_exception(exc, "akshare", _DOMAIN)
    except (KeyError, IndexError, AttributeError, ValueError) as exc:
        # 数据格式异常：AKShare 返回结构不符合预期，不可重试
        raise DataFormatError("akshare", _DOMAIN, f"{exc}")
    except Exception as exc:
        # 其他未知异常
        raise DataSourceUnavailableError("akshare", _DOMAIN, f"{exc}")

    # 空结果：业务正确但无数据，不可重试
    if is_empty_result(df):
        logger.warning("AKShare 股票列表返回空")
        raise DataNotFoundError("akshare", _DOMAIN, "无股票列表数据")

    _stock_list_cache = df
    _stock_list_cache_time = time.time()
    logger.info(f"AKShare 获取股票列表: {len(df)} 只")
    return df


async def fetch_stock_basic_info(code: str) -> dict:
    """获取单只股票基础信息。

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
            return ak.stock_individual_info_em(symbol=code)

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
        logger.warning(f"AKShare 基础信息返回空: code={code}")
        raise DataNotFoundError("akshare", _DOMAIN, f"code={code} 无基础信息")

    result = {}
    for _, row in df.iterrows():
        result[str(row.iloc[0]).strip()] = row.iloc[1]
    return result
