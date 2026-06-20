"""Tushare US ts_code 解析器 — 基于 exchange 字段的权威映射。

替代各 api 模块中的硬编码 ``_to_us_ts_code`` 启发式逻辑。
通过拉取 ``api.us_basic()`` 建立 ``symbol → exchange`` 映射，
再根据 NYSE/NASDAQ/AMEX 精确产出 ts_code 后缀（.N / .O / .A）。

三级缓存（按查找顺序）：
1. 进程内存 ``TTLCache``（默认 300s，命中零开销）
2. MongoDB ``stock_basic_info_us`` 集合（冷启动时使用，由 sync worker 维护）
3. 触发 ``us_basic()`` 远程拉取（受 ``DistributedLock`` 保护，防并发穿透）

未命中 fallback：当本地和远程均无法判断时，默认产出 ``.O`` 并 warn。
"""

import asyncio
import logging
from typing import Dict, Optional

import pandas as pd

from app.data.storage.cache.memory_cache import TTLCache
from app.data.storage.redis.locks import DistributedLock

logger = logging.getLogger(__name__)

# Tushare US exchange 字段 → ts_code 后缀
_EXCHANGE_SUFFIX: Dict[str, str] = {
    "NASDAQ": ".O",
    "NYSE": ".N",
    "AMEX": ".A",
}
_DEFAULT_SUFFIX = ".O"

_MEM_CACHE_KEY = "us_code_resolver:map"
_LOCK_KEY = "us_code_resolver:refresh"
_TTL_SECONDS = 300


class USCodeResolver:
    """单例：把 symbol 转换为 Tushare US ts_code（基于真实 exchange）。"""

    _instance: Optional["USCodeResolver"] = None

    def __new__(cls) -> "USCodeResolver":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._cache = TTLCache(default_ttl=_TTL_SECONDS)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（测试用）。"""
        cls._instance = None

    async def resolve(self, symbol: str, api=None) -> str:
        """返回 Tushare US ts_code。

        Parameters
        ----------
        symbol : str
            原始股票代码，如 ``AAPL`` / ``BABA`` / ``AAPL.O``（已带后缀则原样返回）。
        api : Optional
            Tushare pro_api 实例；为空时仅尝试本地缓存与 MongoDB。
        """
        s = str(symbol).upper().strip()
        if "." in s:
            return s

        mapping = await self._get_mapping(api)
        exchange = mapping.get(s)
        if exchange:
            suffix = _EXCHANGE_SUFFIX.get(exchange.upper(), _DEFAULT_SUFFIX)
            if suffix == _DEFAULT_SUFFIX and exchange.upper() not in _EXCHANGE_SUFFIX:
                logger.warning(
                    "USCodeResolver: symbol=%s 命中未知 exchange=%s，fallback=%s",
                    s,
                    exchange,
                    suffix,
                )
            return f"{s}{suffix}"

        logger.debug(
            "USCodeResolver: symbol=%s 未在映射中找到，fallback=%s",
            s,
            _DEFAULT_SUFFIX,
        )
        return f"{s}{_DEFAULT_SUFFIX}"

    async def _get_mapping(self, api=None) -> Dict[str, str]:
        cached = self._cache.get(_MEM_CACHE_KEY)
        if cached is not None:
            return cached

        from_db = await self._load_from_db()
        if from_db:
            self._cache.set(_MEM_CACHE_KEY, from_db, ttl=_TTL_SECONDS)
            return from_db

        if api is None:
            return {}

        lock = DistributedLock(_LOCK_KEY, ttl=30)
        got = await lock.acquire()
        try:
            if not got:
                # 锁已被其他 worker 占用，短暂等待后重读内存缓存
                await asyncio.sleep(0.5)
                cached = self._cache.get(_MEM_CACHE_KEY)
                if cached is not None:
                    return cached
                return {}

            try:
                from app.data.sources.us.tushare_us.api.us_basic import (
                    fetch_stock_list,
                )
                df = await fetch_stock_list(api)
                mapping = self._df_to_mapping(df)
                self._cache.set(_MEM_CACHE_KEY, mapping, ttl=_TTL_SECONDS)
                return mapping
            except Exception as e:
                logger.warning(f"USCodeResolver: us_basic() 拉取失败: {e}")
                return {}
        finally:
            if got:
                await lock.release()

    @staticmethod
    def _df_to_mapping(df) -> Dict[str, str]:
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            return {}
        mapping: Dict[str, str] = {}
        for _, row in df.iterrows():
            ts_code = str(row.get("ts_code", ""))
            exchange = str(row.get("exchange", "") or "")
            if not ts_code or not exchange:
                continue
            symbol = ts_code.split(".")[0].upper()
            mapping[symbol] = exchange
        return mapping

    async def _load_from_db(self) -> Dict[str, str]:
        try:
            from app.data.storage.mongo.client import get_motor_db
            from app.data.storage.mongo.collections import get_collection_name
            db = get_motor_db()
            coll_name = get_collection_name("basic_info", "US")
            cursor = db[coll_name].find(
                {"market": "US", "data_source": "tushare_us"},
                {"symbol": 1, "exchange": 1, "_id": 0},
            )
            docs = await cursor.to_list(length=None)
            if not docs:
                return {}
            mapping: Dict[str, str] = {}
            for doc in docs:
                sym = doc.get("symbol")
                ex = doc.get("exchange")
                if sym and ex:
                    mapping[str(sym).upper()] = str(ex)
            return mapping
        except Exception as e:
            logger.debug(f"USCodeResolver: MongoDB 读取失败: {e}")
            return {}


async def get_us_ts_code(symbol: str, api=None) -> str:
    """便捷入口：走单例 USCodeResolver 解析 ts_code。"""
    resolver = USCodeResolver()
    return await resolver.resolve(symbol, api=api)
