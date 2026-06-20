"""T-1 收盘价查询工具 — 复权因子计算的辅助查询。

设计要点：

- 按 ``(symbol, ex_date)`` 查询 T-1 收盘价，回溯最多 N 个交易日以应对
  节假日/停牌场景（默认 5 个交易日）
- 内置 ``BoundedLRUCache`` 缓存（默认 512 项 × 1 小时 TTL），避免同一
  symbol 多条 action 时反复回查数据库
- 复用 ``get_collection_name`` 保证与主数据流集合命名一致
- 未命中时缓存"负值"哨兵（``-1.0``），避免连续重复查询空结果

类型一致性：
    daily_quotes 集合中 ``trade_date`` 统一以 ``YYYY-MM-DD`` 字符串存储
    （详见各 adapter ``_parse_date`` 实现）。本模块在查询前对入参 ex_date
    做同样的格式归一化，避免字符串 vs datetime 跨类型 ``$lt`` 比较失效。

仅供 ``AdjFactorCalculator.calculate_from_corporate_actions_async`` 使用，
对调用方保持可选；如果未传入 lookup，仍走原有的"跳过该 action"逻辑。
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Dict, Optional

from app.core.lru_cache import BoundedLRUCache
from app.data.storage.mongo.collections import get_collection_name

logger = logging.getLogger(__name__)

# 命中"未找到"哨兵：复权因子计算据此区分"已查询但无数据"与"未查询"
_NOT_FOUND_SENTINEL = -1.0
# 回溯交易日数量（覆盖春节/国庆 + 停牌等极端场景）
_DEFAULT_LOOKBACK_DAYS = 5


class PrevCloseLookup:
    """按 (symbol, ex_date) 查询 T-1 收盘价，含 LRU 缓存。"""

    def __init__(
        self,
        db: Any,
        market: str,
        cache_size: int = 512,
        cache_ttl: float = 3600.0,
        lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
    ):
        self._db = db
        self._market = market
        self._lookback = max(1, lookback_days)
        self._coll_name = get_collection_name("daily_quotes", market)
        self._cache: BoundedLRUCache = BoundedLRUCache(
            maxsize=cache_size,
            ttl=cache_ttl,
            name=f"prev_close_{market.lower()}",
        )

    async def get(self, symbol: str, ex_date: Any) -> Optional[float]:
        """获取除权日前一日的收盘价。

        Args:
            symbol: 标的代码
            ex_date: 除权日（datetime / date / str）。函数内部会归一化为
                ``YYYY-MM-DD`` 字符串，与 daily_quotes 集合存储格式一致。

        Returns:
            前一交易日 close；查询不到返回 None；失败返回 None 并 warning
        """
        if not symbol or ex_date is None:
            return None

        ex_date_str = _normalize_ex_date(ex_date)
        cache_key = (symbol, ex_date_str)
        cached = self._cache.get(cache_key)
        if cached is not None:
            # 命中：负值哨兵转 None
            return float(cached) if cached > 0 else None

        try:
            cursor = self._db[self._coll_name].find(
                {
                    "symbol": symbol,
                    "trade_date": {"$lt": ex_date_str},
                    # 仅取收盘价字段，避免传输整文档
                },
                {"close": 1, "trade_date": 1, "_id": 0},
            ).sort("trade_date", -1).limit(self._lookback)
            docs = await cursor.to_list(self._lookback)
        except Exception as exc:
            logger.warning(
                "PrevCloseLookup 查询失败 symbol=%s ex_date=%s: %s",
                symbol,
                ex_date_str,
                exc,
            )
            return None

        for doc in docs:
            close = doc.get("close")
            if close is None:
                continue
            try:
                value = float(close)
            except (TypeError, ValueError):
                continue
            if value > 0:
                self._cache.set(cache_key, value)
                return value

        # 未命中任何正向 close：缓存哨兵防止后续重复查询
        self._cache.set(cache_key, _NOT_FOUND_SENTINEL)
        return None

    def stats(self) -> Dict[str, Any]:
        """暴露缓存统计，便于调度端观察命中率。"""
        return self._cache.stats()


def _normalize_ex_date(ex_date: Any) -> str:
    """把任意类型的 ex_date 归一化为 ``YYYY-MM-DD`` 字符串。

    与 daily_quotes 集合的 ``trade_date`` 存储格式保持一致，避免跨类型
    ``$lt`` 比较失效。支持 datetime / date / 各种字符串格式（含 ``YYYYMMDD``）。
    """
    if isinstance(ex_date, datetime):
        return ex_date.strftime("%Y-%m-%d")
    if isinstance(ex_date, date):
        return ex_date.strftime("%Y-%m-%d")
    text = str(ex_date).strip()
    # 处理 "YYYYMMDD" / "YYYY/MM/DD" / "YYYY-MM-DD HH:MM:SS" 等格式
    if len(text) >= 10 and text[4] in ("-", "/"):
        return text[:10].replace("/", "-")
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text[:10] if len(text) >= 10 else text
