"""
Tushare 股票基础信息 API
"""
import asyncio
import logging
from typing import Any, Dict, Optional

import pandas as pd

from app.data.sources.base.exceptions import DataNotFoundError, DataSourceUnavailableError
from app.data.sources.base.mappers import (
    is_empty_result,
    map_network_exception,
    map_tushare_code,
)

from .connection import TushareConnection

logger = logging.getLogger(__name__)

_DOMAIN = "stock_basic"

_STOCK_BASIC_FIELDS = (
    "ts_code,symbol,name,area,industry,market,exchange,list_date,is_hs"
)


async def fetch_stock_list(conn: TushareConnection, market: str = None) -> Optional[pd.DataFrame]:
    """获取 A 股股票列表"""
    if not conn.is_available():
        return None

    params: Dict[str, Any] = {"list_status": "L", "fields": _STOCK_BASIC_FIELDS}
    if market == "CN":
        params["exchange"] = "SSE,SZSE"

    try:
        df = await asyncio.to_thread(conn.api.stock_basic, **params)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "tushare", _DOMAIN)
    except Exception as exc:
        error_code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
        mapped = map_tushare_code(error_code, "tushare", _DOMAIN, str(exc))
        if mapped is not None:
            raise mapped
        raise DataSourceUnavailableError("tushare", _DOMAIN, str(exc))

    if is_empty_result(df):
        logger.warning("Tushare 股票列表返回空")
        raise DataNotFoundError("tushare", _DOMAIN, "无数据")

    logger.info(f"Tushare 获取股票列表: {len(df)} 只")
    return df


async def fetch_stock_basic_info(
    conn: TushareConnection, ts_code: str
) -> Optional[pd.DataFrame]:
    """获取单只股票基础信息"""
    if not conn.is_available():
        return None

    try:
        if ts_code.endswith(".HK"):
            df = await asyncio.to_thread(conn.api.hk_basic, ts_code=ts_code)
        else:
            df = await asyncio.to_thread(
                conn.api.stock_basic,
                ts_code=ts_code,
                fields=_STOCK_BASIC_FIELDS + ",act_name,act_ent_type",
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
        logger.warning(f"Tushare 基础信息返回空: ts_code={ts_code}")
        raise DataNotFoundError("tushare", _DOMAIN, f"ts_code={ts_code} 不存在")

    return df
