"""
Tushare 每日指标 API（PE/PB/市值/换手率等）
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

_DOMAIN = "daily_indicators"

_DAILY_BASIC_FIELDS = (
    "ts_code,trade_date,total_mv,circ_mv,pe,pb,turnover_rate,volume_ratio,pe_ttm,pb_mrq,ps,ps_ttm"
)


async def fetch_daily_indicators(
    conn: TushareConnection, trade_date: str
) -> Optional[pd.DataFrame]:
    """获取全市场每日指标"""
    if not conn.is_available():
        return None

    date_str = trade_date.replace("-", "")
    try:
        df = await asyncio.to_thread(
            conn.api.daily_basic,
            trade_date=date_str,
            fields=_DAILY_BASIC_FIELDS,
        )
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "tushare", _DOMAIN)
    except Exception as exc:
        error_code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
        mapped = map_tushare_code(error_code, "tushare", _DOMAIN, str(exc))
        if mapped is not None:
            raise mapped
        raise DataSourceUnavailableError(
            "tushare", _DOMAIN, f"trade_date={trade_date}: {exc}"
        )

    if is_empty_result(df):
        logger.warning(f"Tushare 每日指标返回空: trade_date={trade_date}")
        raise DataNotFoundError("tushare", _DOMAIN, f"trade_date={trade_date} 无数据")

    logger.info(f"Tushare 每日指标: {trade_date} {len(df)} 条")
    return df


async def fetch_daily_indicators_by_symbol(
    conn: TushareConnection, ts_code: str, start_date: str = None, end_date: str = None
) -> Optional[pd.DataFrame]:
    """获取单只股票每日指标"""
    if not conn.is_available():
        return None

    params = {"ts_code": ts_code, "fields": _DAILY_BASIC_FIELDS}
    if start_date:
        params["start_date"] = start_date.replace("-", "")
    if end_date:
        params["end_date"] = end_date.replace("-", "")

    try:
        df = await asyncio.to_thread(conn.api.daily_basic, **params)
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
        logger.warning(f"Tushare 每日指标返回空: ts_code={ts_code}")
        raise DataNotFoundError("tushare", _DOMAIN, f"ts_code={ts_code} 无数据")

    logger.info(f"Tushare 每日指标: {ts_code} {len(df)} 条")
    return df
