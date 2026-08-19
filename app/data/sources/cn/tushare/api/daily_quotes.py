"""
Tushare 日线行情 API

fetch_daily_quotes 使用 ts.pro_bar 模块函数（非 pro_api 方法，
带复权参数），保留独立调用体；fetch_realtime_batch 的调用模板
收敛在 app/data/sources/tushare_common/caller.py。
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
from app.data.sources.tushare_common.caller import call_tushare
from app.utils.time_utils import now_config_tz, format_date_compact

from .connection import TushareConnection

logger = logging.getLogger(__name__)

try:
    import tushare as ts
except ImportError:
    ts = None

_DOMAIN = "daily_quotes"
_SOURCE = "tushare"


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
        # 港股行情已独立为 tushare_hk 源（独立 Token/积分），CN 源不再处理 .HK 代码
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
        raise map_network_exception(exc, _SOURCE, _DOMAIN)
    except Exception as exc:
        error_code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
        mapped = map_tushare_code(error_code, _SOURCE, _DOMAIN, str(exc))
        if mapped is not None:
            raise mapped
        raise DataSourceUnavailableError(
            _SOURCE, _DOMAIN, f"ts_code={ts_code}: {exc}"
        )

    if is_empty_result(df):
        logger.warning(f"Tushare 返回空行情: {ts_code} {start_str}-{end_str}")
        raise DataNotFoundError(
            _SOURCE, _DOMAIN, f"ts_code={ts_code} {start_str}-{end_str} 无数据"
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
    return await call_tushare(
        conn,
        "rt_k",
        _SOURCE,
        "realtime_quotes",
        ts_code="3*.SZ,6*.SH,0*.SZ,9*.BJ",
    )


def _format_compact(date_str: str) -> str:
    """YYYY-MM-DD -> YYYYMMDD"""
    return str(date_str).replace("-", "")
