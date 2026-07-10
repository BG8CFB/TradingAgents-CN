"""
Tushare 股权质押 API

接口: pledge_stat (股权质押统计) + pledge_detail (股权质押明细)
要求: >= 120 积分
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

_DOMAIN = "pledge"


async def fetch_pledge_stat(
    conn: TushareConnection,
    ts_code: str = None,
    end_date: str = None,
) -> Optional[pd.DataFrame]:
    """获取股权质押统计数据（pledge_stat）"""
    if not conn.is_available():
        return None

    kwargs = {}
    if ts_code:
        kwargs["ts_code"] = ts_code
    if end_date:
        kwargs["end_date"] = str(end_date).replace("-", "")

    try:
        df = await asyncio.to_thread(conn.api.pledge_stat, **kwargs)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "tushare", _DOMAIN)
    except Exception as exc:
        error_code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
        mapped = map_tushare_code(error_code, "tushare", _DOMAIN, str(exc))
        if mapped is not None:
            raise mapped
        raise DataSourceUnavailableError("tushare", _DOMAIN, str(exc))

    if is_empty_result(df):
        raise DataNotFoundError("tushare", _DOMAIN, f"{kwargs} 无数据")

    logger.info(f"Tushare 股权质押统计: {len(df)} 条")
    return df


async def fetch_pledge_detail(
    conn: TushareConnection,
    ts_code: str = None,
    end_date: str = None,
) -> Optional[pd.DataFrame]:
    """获取股权质押明细数据（pledge_detail）"""
    if not conn.is_available():
        return None

    kwargs = {}
    if ts_code:
        kwargs["ts_code"] = ts_code
    if end_date:
        kwargs["end_date"] = str(end_date).replace("-", "")

    try:
        df = await asyncio.to_thread(conn.api.pledge_detail, **kwargs)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "tushare", _DOMAIN)
    except Exception as exc:
        error_code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
        mapped = map_tushare_code(error_code, "tushare", _DOMAIN, str(exc))
        if mapped is not None:
            raise mapped
        raise DataSourceUnavailableError("tushare", _DOMAIN, str(exc))

    if is_empty_result(df):
        raise DataNotFoundError("tushare", _DOMAIN, f"{kwargs} 无数据")

    logger.info(f"Tushare 股权质押明细: {len(df)} 条")
    return df
