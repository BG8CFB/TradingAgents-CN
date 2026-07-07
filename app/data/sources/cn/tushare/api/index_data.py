"""
Tushare 指数数据 API

接口: index_daily (指数日线行情) + index_weight (指数成分和权重)
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

_DOMAIN = "index_data"


async def fetch_index_daily(
    conn: TushareConnection,
    ts_code: str,
    start_date: str = None,
    end_date: str = None,
) -> Optional[pd.DataFrame]:
    """获取指数日线行情（index_daily）"""
    if not conn.is_available():
        return None

    kwargs = {"ts_code": ts_code}
    if start_date:
        kwargs["start_date"] = str(start_date).replace("-", "")
    if end_date:
        kwargs["end_date"] = str(end_date).replace("-", "")

    try:
        df = await asyncio.to_thread(conn.api.index_daily, **kwargs)
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

    logger.info(f"Tushare 指数日线: {ts_code} {len(df)} 条")
    return df


async def fetch_index_weight(
    conn: TushareConnection,
    index_code: str = None,
    trade_date: str = None,
    start_date: str = None,
    end_date: str = None,
) -> Optional[pd.DataFrame]:
    """获取指数成分和权重（index_weight）

    月度数据，建议 start_date 和 end_date 分别输入当月第一天和最后一天。
    """
    if not conn.is_available():
        return None

    kwargs = {}
    if index_code:
        kwargs["index_code"] = index_code
    if trade_date:
        kwargs["trade_date"] = str(trade_date).replace("-", "")
    elif start_date:
        kwargs["start_date"] = str(start_date).replace("-", "")
        kwargs["end_date"] = str(end_date or start_date).replace("-", "")

    try:
        df = await asyncio.to_thread(conn.api.index_weight, **kwargs)
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

    logger.info(f"Tushare 指数权重: {len(df)} 条")
    return df
