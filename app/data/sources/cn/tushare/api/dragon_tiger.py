"""
Tushare 龙虎榜 API

接口: top_list (龙虎榜每日明细) + top_inst (龙虎榜机构明细)
要求: >= 120 积分
"""
import asyncio
import logging
from datetime import timedelta
from typing import Optional

import pandas as pd

from app.core.lru_cache import BoundedLRUCache
from app.data.sources.base.exceptions import DataNotFoundError, DataSourceUnavailableError
from app.data.sources.base.mappers import (
    is_empty_result,
    map_network_exception,
    map_tushare_code,
)
from app.utils.time_utils import now_config_tz

from .connection import TushareConnection

logger = logging.getLogger(__name__)

_DOMAIN = "dragon_tiger"

# 单股扫描时的逐日限流间隔（秒）。30 日循环每轮必须 sleep，避免触发 Tushare 反爬。
_SYMBOL_THROTTLE_SECONDS = 0.3

# 按 symbol 缓存龙虎榜结果，避免 engine tool 在 4 个分析师并发场景下
# 对同一 ts_code 发起 30 次 tushare.top_list 调用导致 N+1 问题
# maxsize=128：覆盖典型 watchlist（≤100 只）；TTL=1h：跨任务阶段可复用
_symbol_cache: BoundedLRUCache = BoundedLRUCache(
    maxsize=128, ttl=3600.0, name="dragon_tiger_by_symbol",
)
# 缓存未命中的哨兵（避免反复重试 30 天扫描后才知道无数据）
_NOT_FOUND_SENTINEL = "__not_found__"


async def fetch_dragon_tiger(
    conn: TushareConnection,
    trade_date: str = None,
    start_date: str = None,
    end_date: str = None,
    ts_code: str = None,
) -> Optional[pd.DataFrame]:
    """
    获取龙虎榜数据

    支持按日期或按股票代码查询。按股票代码查询时会扫描最近 30 个交易日，
    命中 ``_symbol_cache`` 时直接返回缓存（TTL=1h），避免 N+1。
    """
    if not conn.is_available():
        return None

    if ts_code:
        cached = _symbol_cache.get(ts_code)
        if cached is _NOT_FOUND_SENTINEL:
            raise DataNotFoundError(
                "tushare",
                _DOMAIN,
                f"ts_code={ts_code} 近 30 天无记录（缓存命中）",
            )
        if cached is not None:
            logger.debug(f"Tushare 龙虎榜({ts_code}): 缓存命中 {len(cached)} 条")
            return cached
        df = await _fetch_by_symbol(conn, ts_code)
        _symbol_cache.set(ts_code, df)
        return df

    return await _fetch_by_date(conn, trade_date, start_date, end_date)


async def _fetch_by_date(
    conn: TushareConnection,
    trade_date: str = None,
    start_date: str = None,
    end_date: str = None,
) -> Optional[pd.DataFrame]:
    """按日期获取龙虎榜"""
    kwargs = {}
    if trade_date:
        kwargs["trade_date"] = str(trade_date).replace("-", "")
    elif start_date:
        kwargs["start_date"] = str(start_date).replace("-", "")
        kwargs["end_date"] = str(end_date or start_date).replace("-", "")

    try:
        df = await asyncio.to_thread(conn.api.top_list, **kwargs)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "tushare", _DOMAIN)
    except Exception as exc:
        error_code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
        mapped = map_tushare_code(error_code, "tushare", _DOMAIN, str(exc))
        if mapped is not None:
            raise mapped
        raise DataSourceUnavailableError("tushare", _DOMAIN, str(exc))

    if is_empty_result(df):
        logger.debug(f"Tushare 龙虎榜(日期)为空: {kwargs}")
        raise DataNotFoundError("tushare", _DOMAIN, f"{kwargs} 无数据")

    logger.info(f"Tushare 龙虎榜(日期): {len(df)} 条")
    return df


async def _fetch_by_symbol(
    conn: TushareConnection,
    ts_code: str,
) -> Optional[pd.DataFrame]:
    """按股票代码扫描最近龙虎榜记录

    每日的拉取可能因限流/单日无数据而失败，逐日重试。最终若 30 天内均无记录，
    抛 DataNotFoundError；若中途遇到鉴权/积分异常则直接透传。
    """
    symbol = ts_code.split(".")[0] if "." in ts_code else ts_code

    last_business_error: Optional[Exception] = None

    for days_back in range(0, 30):
        check_date = (now_config_tz() - timedelta(days=days_back)).strftime("%Y%m%d")
        try:
            df = await asyncio.to_thread(conn.api.top_list, trade_date=check_date)
        except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
            # 单日网络异常不影响后续日期，记录后继续；但仍需 sleep 以遵守限流
            last_business_error = map_network_exception(exc, "tushare", _DOMAIN)
            await asyncio.sleep(_SYMBOL_THROTTLE_SECONDS)
            continue
        except Exception as exc:
            error_code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
            mapped = map_tushare_code(error_code, "tushare", _DOMAIN, str(exc))
            if mapped is not None:
                # 鉴权/积分类异常：不可能通过重试解决，直接透传
                raise mapped
            # 其他未知异常：记录后继续尝试下一日
            last_business_error = DataSourceUnavailableError(
                "tushare", _DOMAIN, f"{check_date}: {exc}"
            )
            await asyncio.sleep(_SYMBOL_THROTTLE_SECONDS)
            continue

        # 每轮调用后限流 sleep（包括成功和空数据两种情况）
        if df is not None and not df.empty:
            # 精确匹配：ts_code 形如 "000001.SH"，按点号拆分后取前缀比较
            filtered = df[df["ts_code"].astype(str).str.split(".").str[0] == symbol]
            if not filtered.empty:
                logger.info(
                    f"Tushare 龙虎榜({ts_code}): {len(filtered)} 条 ({check_date})"
                )
                return filtered
        await asyncio.sleep(_SYMBOL_THROTTLE_SECONDS)

    logger.debug(f"Tushare 龙虎榜: {ts_code} 近 30 天无记录")
    # 缓存"未找到"哨兵（TTL 1h），避免短时间内重复触发 30 天扫描
    _symbol_cache.set(ts_code, _NOT_FOUND_SENTINEL)
    # 若扫描过程中有非致命异常，则附带原始异常信息以便排障
    if last_business_error is not None:
        raise DataNotFoundError(
            "tushare",
            _DOMAIN,
            f"ts_code={ts_code} 近 30 天无记录 (last_err={last_business_error})",
        )
    raise DataNotFoundError("tushare", _DOMAIN, f"ts_code={ts_code} 近 30 天无记录")
