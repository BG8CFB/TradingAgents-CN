"""
Tushare 分钟线 API

接口: stk_mins
要求: >= 2000 积分, 限频 1 次/小时
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

_DOMAIN = "intraday_quotes"


async def fetch_intraday_quotes(
    conn: TushareConnection,
    ts_code: str,
    freq: str = "30min",
    limit: int = 500,
) -> Optional[pd.DataFrame]:
    """
    获取分钟级行情

    注意: stk_mins 限频 1次/小时，适合定时批量同步，不适合实时调用。
    """
    if not conn.is_available():
        return None

    freq_map = {"1min": "1", "5min": "5", "15min": "15", "30min": "30", "60min": "60"}
    freq_code = freq_map.get(freq, "30")

    try:
        df = await asyncio.to_thread(
            conn.api.stk_mins,
            ts_code=ts_code,
            freq=freq_code,
            limit=limit,
        )
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "tushare", _DOMAIN)
    except Exception as exc:
        error_code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
        mapped = map_tushare_code(error_code, "tushare", _DOMAIN, str(exc))
        if mapped is not None:
            raise mapped
        raise DataSourceUnavailableError(
            "tushare", _DOMAIN, f"ts_code={ts_code}: {exc}"
        )

    if is_empty_result(df):
        logger.debug(f"Tushare 分钟线为空: {ts_code}")
        raise DataNotFoundError("tushare", _DOMAIN, f"ts_code={ts_code} 无数据")

    logger.info(f"Tushare 分钟线: {ts_code} {len(df)} 条 ({freq})")
    return df
