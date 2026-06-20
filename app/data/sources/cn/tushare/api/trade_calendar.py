"""
Tushare 交易日历 API
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

_DOMAIN = "trade_calendar"


async def fetch_trade_calendar(
    conn: TushareConnection,
    exchange: str = "SSE",
    start_date: str = None,
    end_date: str = None,
) -> Optional[pd.DataFrame]:
    """获取交易日历"""
    if not conn.is_available():
        return None

    params: dict = {"exchange": exchange}
    if start_date:
        params["start_date"] = start_date.replace("-", "")
    if end_date:
        params["end_date"] = end_date.replace("-", "")

    try:
        df = await asyncio.to_thread(conn.api.trade_cal, **params)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "tushare", _DOMAIN)
    except Exception as exc:
        error_code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
        mapped = map_tushare_code(error_code, "tushare", _DOMAIN, str(exc))
        if mapped is not None:
            raise mapped
        raise DataSourceUnavailableError("tushare", _DOMAIN, str(exc))

    if is_empty_result(df):
        logger.warning(f"Tushare 交易日历返回空: exchange={exchange}")
        raise DataNotFoundError("tushare", _DOMAIN, f"exchange={exchange} 无数据")

    logger.info(f"Tushare 交易日历: {exchange} {len(df)} 条")
    return df
