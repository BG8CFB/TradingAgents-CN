"""
Tushare 日线行情 API

fetch_daily_quotes 使用 ts.pro_bar 模块函数（非 pro_api 方法，
带复权参数），保留独立调用体；fetch_realtime_batch 的调用模板
收敛在 app/data/sources/tushare_common/caller.py。
"""
import asyncio
import logging
from datetime import timedelta
from typing import Optional

import pandas as pd

from app.data.sources.base.exceptions import DataNotFoundError, DataSourceUnavailableError
from app.data.sources.base.mappers import (
    is_empty_result,
    map_network_exception,
    map_tushare_code,
)
from app.data.sources.tushare_common.caller import call_tushare, call_tushare_paged
from app.utils.time_utils import now_config_tz, format_date_compact

from .connection import TushareConnection

logger = logging.getLogger(__name__)

try:
    import tushare as ts
except ImportError:
    ts = None

_DOMAIN = "daily_quotes"
_SOURCE = "tushare"

# daily 接口（未复权日线）按 trade_date 批量时的字段集：
# 与 pro_bar qfq 输出对齐（除复权价外字段同名），adapter 按既有
# adapt_daily_quotes 语义映射；amount 单位千元、vol 单位手。
_DAILY_TRADE_DATE_FIELDS = (
    "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"
)


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
    """批量获取全市场实时行情（rt_k 接口，需单独开通实时行情权限）"""
    return await call_tushare(
        conn,
        "rt_k",
        _SOURCE,
        "realtime_quotes",
        ts_code="3*.SZ,6*.SH,0*.SZ,9*.BJ",
    )


async def fetch_daily_quotes_batch(
    conn: TushareConnection, trade_date: str
) -> Optional[pd.DataFrame]:
    """按交易日一次拉全市场未复权日线（daily 接口，分页）。

    与逐 symbol 的 pro_bar（复权价）互补：调度同步只需要原始 OHLCV，
    复权由 adj_factors 消费侧计算。5572 次/symbol 调用 → 2 页调用，
    在 500 次/分钟配额下从 11+ 分钟降到秒级。
    """
    date_str = str(trade_date).replace("-", "")
    return await call_tushare_paged(
        conn,
        "daily",
        _SOURCE,
        _DOMAIN,
        f"trade_date={trade_date}",
        trade_date=date_str,
        fields=_DAILY_TRADE_DATE_FIELDS,
    )

# 主要指数（market_quotes 里以 6 位 symbol 存储，供 get_index_data 等工具读取）
MAIN_INDEXES = (
    ("000001.SH", "上证指数"),
    ("399001.SZ", "深证成指"),
    ("399006.SZ", "创业板指"),
    ("000300.SH", "沪深300"),
    ("000905.SH", "中证500"),
)


async def fetch_index_quotes(conn: TushareConnection, days_back: int = 10) -> Optional[pd.DataFrame]:
    """主要指数日线（index_daily）→ market_quotes 形状。

    rt_k（实时行情）只覆盖个股且需单独权限，指数取不到；而 index_daily 属于
    常规积分接口。取最近若干交易日后按指数取最新一根，保证节假日也有值。
    """
    end_date = format_date_compact(now_config_tz())
    start_date = format_date_compact(now_config_tz() - timedelta(days=days_back))

    frames = []
    for ts_code, _name in MAIN_INDEXES:
        try:
            df = await call_tushare(
                conn,
                "index_daily",
                _SOURCE,
                "index_quotes",
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date,
            )
            if df is not None and not df.empty:
                frames.append(df)
        except Exception as exc:  # noqa: BLE001 - 单个指数失败不影响其它
            logger.debug(f"指数日线获取失败 {ts_code}: {exc}")

    if not frames:
        return None

    merged = pd.concat(frames, ignore_index=True)
    if "trade_date" in merged.columns:
        merged = (
            merged.sort_values("trade_date")
            .groupby("ts_code", as_index=False)
            .tail(1)
            .reset_index(drop=True)
        )
    return merged


def _format_compact(date_str: str) -> str:
    """YYYY-MM-DD -> YYYYMMDD"""
    return str(date_str).replace("-", "")
