"""
Tushare 停复牌 API

接口: suspend_d (每日停复牌信息)
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

_DOMAIN = "trading_status"


async def fetch_suspend_info(
    conn: TushareConnection,
    ts_code: str = None,
    trade_date: str = None,
    start_date: str = None,
    end_date: str = None,
) -> Optional[pd.DataFrame]:
    """获取每日停复牌信息（suspend_d）"""
    if not conn.is_available():
        return None

    kwargs = {}
    if ts_code:
        kwargs["ts_code"] = ts_code
    if trade_date:
        kwargs["trade_date"] = str(trade_date).replace("-", "")
    elif start_date:
        kwargs["start_date"] = str(start_date).replace("-", "")
        kwargs["end_date"] = str(end_date or start_date).replace("-", "")

    try:
        df = await asyncio.to_thread(conn.api.suspend_d, **kwargs)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "tushare", _DOMAIN)
    except Exception as exc:
        error_code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
        mapped = map_tushare_code(error_code, "tushare", _DOMAIN, str(exc))
        if mapped is not None:
            raise mapped
        raise DataSourceUnavailableError("tushare", _DOMAIN, str(exc))

    if is_empty_result(df):
        logger.debug(f"Tushare 停复牌为空: {kwargs}")
        raise DataNotFoundError("tushare", _DOMAIN, f"{kwargs} 无数据")

    logger.info(f"Tushare 停复牌: {len(df)} 条")
    return df
