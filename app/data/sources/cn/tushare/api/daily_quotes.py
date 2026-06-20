"""
Tushare 日线行情 API
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
from app.utils.time_utils import now_config_tz, format_date_compact

from .connection import TushareConnection

logger = logging.getLogger(__name__)

try:
    import tushare as ts
except ImportError:
    ts = None

_DOMAIN = "daily_quotes"


async def fetch_daily_quotes(
    conn: TushareConnection,
    ts_code: str,
    start_date: str,
    end_date: str,
    period: str = "daily",
) -> Optional[pd.DataFrame]:
    """获取日线/周线/月线行情（前复权）"""
    if not conn.is_available():
        return None

    start_str = _format_compact(start_date)
    end_str = _format_compact(end_date) if end_date else format_date_compact(now_config_tz())

    freq_map = {"daily": "D", "weekly": "W", "monthly": "M"}
    freq = freq_map.get(period, "D")

    try:
        if ts_code.endswith(".HK"):
            df = await asyncio.to_thread(
                conn.api.hk_daily,
                ts_code=ts_code,
                start_date=start_str,
                end_date=end_str,
            )
        else:
            df = await asyncio.to_thread(
                ts.pro_bar,
                ts_code=ts_code,
                api=conn.api,
                start_date=start_str,
                end_date=end_str,
                freq=freq,
                adj="qfq",
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
        logger.warning(f"Tushare 返回空行情: {ts_code} {start_str}-{end_str}")
        raise DataNotFoundError(
            "tushare", _DOMAIN, f"ts_code={ts_code} {start_str}-{end_str} 无数据"
        )

    # 统一列名
    if "vol" in df.columns:
        df = df.rename(columns={"vol": "volume"})
    if "trade_time" in df.columns:
        df = df.sort_values("trade_time").reset_index(drop=True)

    logger.info(f"Tushare 获取行情: {ts_code} {len(df)} 条")
    return df


async def fetch_realtime_batch(conn: TushareConnection) -> Optional[pd.DataFrame]:
    """批量获取全市场实时行情（rt_k 接口）"""
    if not conn.is_available():
        return None

    try:
        df = await asyncio.to_thread(
            conn.api.rt_k,
            ts_code="3*.SZ,6*.SH,0*.SZ,9*.BJ",
        )
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "tushare", "realtime_quotes")
    except Exception as exc:
        error_code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
        mapped = map_tushare_code(error_code, "tushare", "realtime_quotes", str(exc))
        if mapped is not None:
            raise mapped
        raise DataSourceUnavailableError("tushare", "realtime_quotes", str(exc))

    if is_empty_result(df):
        logger.warning("Tushare 实时行情返回空")
        raise DataNotFoundError("tushare", "realtime_quotes", "无数据")

    logger.info(f"Tushare 实时行情: {len(df)} 只")
    return df


def _format_compact(date_str: str) -> str:
    """YYYY-MM-DD -> YYYYMMDD"""
    return str(date_str).replace("-", "")
