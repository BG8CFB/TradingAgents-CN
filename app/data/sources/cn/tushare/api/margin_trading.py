"""
Tushare 融资融券 API

接口: margin_detail (个股融资融券明细)
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

_DOMAIN = "margin_trading"


async def fetch_margin_detail(
    conn: TushareConnection,
    ts_code: str,
    start_date: str = None,
    end_date: str = None,
    limit: int = 60,
) -> Optional[pd.DataFrame]:
    """获取个股融资融券明细"""
    if not conn.is_available():
        return None

    kwargs = {"ts_code": ts_code}
    if start_date:
        kwargs["start_date"] = str(start_date).replace("-", "")
    if end_date:
        kwargs["end_date"] = str(end_date).replace("-", "")
    if not start_date and not end_date:
        kwargs["limit"] = limit

    try:
        df = await asyncio.to_thread(conn.api.margin_detail, **kwargs)
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
        logger.debug(f"Tushare 融资融券明细为空: {ts_code}")
        raise DataNotFoundError("tushare", _DOMAIN, f"ts_code={ts_code} 无数据")

    logger.info(f"Tushare 融资融券明细: {ts_code} {len(df)} 条")
    return df
