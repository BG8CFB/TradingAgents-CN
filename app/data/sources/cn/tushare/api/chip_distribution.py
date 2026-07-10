"""
Tushare 筹码分布 API

接口: cyq_perf (每日筹码及胜率) + cyq_chips (每日筹码分布)
要求: >= 2000 积分
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

from app.data.sources.base.exceptions import DataNotFoundError, DataSourceUnavailableError
from app.data.sources.base.mappers import (
    is_empty_result,
    map_network_exception,
    map_tushare_code,
)

from .connection import TushareConnection

logger = logging.getLogger(__name__)

_DOMAIN = "chip_distribution"


async def fetch_chip_perf(
    conn: TushareConnection,
    ts_code: str,
    trade_date: str = None,
    start_date: str = None,
    end_date: str = None,
) -> Optional[pd.DataFrame]:
    """获取每日筹码及胜率（cyq_perf）"""
    if not conn.is_available():
        return None

    kwargs = {"ts_code": ts_code}
    if trade_date:
        kwargs["trade_date"] = str(trade_date).replace("-", "")
    elif start_date:
        kwargs["start_date"] = str(start_date).replace("-", "")
        kwargs["end_date"] = str(end_date or start_date).replace("-", "")

    try:
        df = await asyncio.to_thread(conn.api.cyq_perf, **kwargs)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "tushare", _DOMAIN)
    except Exception as exc:
        error_code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
        mapped = map_tushare_code(error_code, "tushare", _DOMAIN, str(exc))
        if mapped is not None:
            raise mapped
        raise DataSourceUnavailableError("tushare", _DOMAIN, str(exc))

    if is_empty_result(df):
        raise DataNotFoundError("tushare", _DOMAIN, f"ts_code={ts_code} 无数据")

    logger.info(f"Tushare 筹码胜率: {ts_code} {len(df)} 条")
    return df


async def fetch_chip_distribution(
    conn: TushareConnection,
    ts_code: str,
    trade_date: str = None,
) -> Optional[pd.DataFrame]:
    """获取每日筹码分布（cyq_chips）"""
    if not conn.is_available():
        return None

    kwargs = {"ts_code": ts_code}
    if trade_date:
        kwargs["trade_date"] = str(trade_date).replace("-", "")

    try:
        df = await asyncio.to_thread(conn.api.cyq_chips, **kwargs)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "tushare", _DOMAIN)
    except Exception as exc:
        error_code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
        mapped = map_tushare_code(error_code, "tushare", _DOMAIN, str(exc))
        if mapped is not None:
            raise mapped
        raise DataSourceUnavailableError("tushare", _DOMAIN, str(exc))

    if is_empty_result(df):
        raise DataNotFoundError("tushare", _DOMAIN, f"ts_code={ts_code} 无数据")

    logger.info(f"Tushare 筹码分布: {ts_code} {len(df)} 条")
    return df
