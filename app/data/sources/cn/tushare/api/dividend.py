"""
Tushare 分红送股 API

接口: dividend
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

_DOMAIN = "dividend"


async def fetch_dividend(
    conn: TushareConnection,
    ts_code: str = None,
    record_date: str = None,
    ex_date: str = None,
) -> Optional[pd.DataFrame]:
    """获取分红送股数据"""
    if not conn.is_available():
        return None

    kwargs = {}
    if ts_code:
        kwargs["ts_code"] = ts_code
    if record_date:
        kwargs["record_date"] = str(record_date).replace("-", "")
    if ex_date:
        kwargs["ex_date"] = str(ex_date).replace("-", "")

    try:
        df = await asyncio.to_thread(conn.api.dividend, **kwargs)
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

    logger.info(f"Tushare 分红送股: {len(df)} 条")
    return df
