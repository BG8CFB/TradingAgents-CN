"""统一的有界 LRU 缓存基类。

替代所有手写 OrderedDict + Lock 的代码（reports_service、analysis_service、
task_manager、memory_state_manager 等），保证：

- 线程安全（threading.Lock 保护内部 OrderedDict）
- 可选 TTL（懒清理，命中检查过期）
- maxsize 上限自动淘汰最旧项
- 显式 invalidate(key) / clear()
- stats() 返回命中/未命中统计

使用示例::

    from app.core.lru_cache import BoundedLRUCache

    cache = BoundedLRUCache(maxsize=512, ttl=300)
    cache.set("foo", "bar")
    value = cache.get("foo")  # "bar"
    cache.invalidate("foo")
    cache.clear()
    stats = cache.stats()  # {"hits": 1, "misses": 1, "size": 0, "evictions": 0}
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Dict, Hashable, Optional

logger = logging.getLogger(__name__)


class BoundedLRUCache:
    """线程安全 + 可选 TTL 的有界 LRU 缓存。"""

    def __init__(
        self,
        maxsize: int = 512,
        ttl: Optional[float] = None,
        *,
        name: str = "",
        on_evict: Optional[Callable[[Any, Any], None]] = None,
    ) -> None:
        if maxsize < 1:
            raise ValueError(f"maxsize 必须 >= 1, got {maxsize}")
        if ttl is not None and ttl <= 0:
            raise ValueError(f"ttl 必须 > 0 或 None, got {ttl}")
        self._maxsize = maxsize
        self._ttl = ttl
        self._name = name or self.__class__.__name__
        self._data: "OrderedDict[Hashable, tuple[Any, float]]" = OrderedDict()
        self._lock = threading.Lock()
        # 统计
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._expired = 0
        # 淘汰/失效回调：同步签名 (key, value) -> None；异常会被捕获并降级为 warning
        self._on_evict = on_evict

    # ── 核心读写 ──────────────────────────────────────────────────

    def get(self, key: Hashable) -> Optional[Any]:
        """读取缓存值。

        - TTL 过期返回 None（并清理）
        - 命中会刷新最近使用顺序
        """
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self._misses += 1
                return None
            value, expires_at = entry
            if expires_at is not None and time.monotonic() > expires_at:
                # 过期：惰性删除
                self._data.pop(key, None)
                self._expired += 1
                self._misses += 1
                return None
            # 命中：刷新使用顺序
            self._data.move_to_end(key)
            self._hits += 1
            return value

    def set(self, key: Hashable, value: Any, ttl: Optional[float] = None) -> None:
        """写入缓存值。

        Args:
            key: 缓存键
            value: 缓存值
            ttl: 可选，覆盖实例级 TTL（秒）
        """
        effective_ttl = ttl if ttl is not None else self._ttl
        expires_at = (
            time.monotonic() + effective_ttl if effective_ttl else None
        )
        with self._lock:
            if key in self._data:
                # 已存在：更新 + 刷新使用顺序
                self._data[key] = (value, expires_at)
                self._data.move_to_end(key)
                return
            # 新增：先放入再检查淘汰
            self._data[key] = (value, expires_at)
            while len(self._data) > self._maxsize:
                # popitem(last=False) 淘汰最旧项
                evicted_key, (evicted_value, _) = self._data.popitem(last=False)
                self._evictions += 1
                self._fire_evict_callback(evicted_key, evicted_value)

    def invalidate(self, key: Hashable) -> bool:
        """显式失效单条记录。返回是否实际删除。"""
        with self._lock:
            entry = self._data.pop(key, None)
            if entry is None:
                return False
            value, _ = entry
            self._fire_evict_callback(key, value)
            return True

    def clear(self) -> int:
        """清空所有缓存。返回清理数量。"""
        with self._lock:
            items = list(self._data.items())
            count = len(items)
            self._data.clear()
        # 锁外触发回调，避免持锁 await/IO（虽然回调本身是同步的）
        for k, (v, _) in items:
            self._fire_evict_callback(k, v)
        return count

    # ── 回调 ────────────────────────────────────────────────────

    def _fire_evict_callback(self, key: Any, value: Any) -> None:
        """触发驱逐/失效回调。异常被捕获并降级为 warning，避免污染调用方。"""
        if self._on_evict is None:
            return
        try:
            self._on_evict(key, value)
        except Exception as e:
            logger.warning(
                "BoundedLRUCache[%s] on_evict 回调失败 key=%r: %s",
                self._name,
                key,
                e,
            )

    # ── 元信息 ────────────────────────────────────────────────────

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    def __contains__(self, key: object) -> bool:
        """``key in cache`` 检查：仅返回 True/False，不做副作用。

        旧实现会在过期时 ``pop``，导致 ``in`` 表达式与 ``get`` 语义混淆
        （``in`` 不应改变内部状态）。过期清理收敛到 ``get``；本方法只读，
        让 ``key in cache`` 即使在并发场景也是真正"无副作用"的成员检查。
        """
        with self._lock:
            entry = self._data.get(key)  # type: ignore[arg-type]
            if entry is None:
                return False
            _, expires_at = entry
            # 过期不在此清理（避免 in 触发 mutation）；下次 get() 时会被回收
            if expires_at is not None and time.monotonic() > expires_at:
                return False
            return True

    def stats(self) -> Dict[str, int]:
        """返回统计信息。"""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total) if total else 0
            return {
                "name": self._name,
                "size": len(self._data),
                "maxsize": self._maxsize,
                "ttl": self._ttl,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(hit_rate, 4),
                "evictions": self._evictions,
                "expired": self._expired,
            }

    # ── 迭代（只读快照）─────────────────────────────────────────

    def items(self):
        """返回 (key, value) 列表快照。"""
        with self._lock:
            now = time.monotonic()
            result = []
            for k, (v, expires_at) in self._data.items():
                if expires_at is not None and now > expires_at:
                    continue
                result.append((k, v))
            return result

    def values(self):
        """返回所有值的列表快照。"""
        return [v for _, v in self.items()]

    def keys(self):
        """返回所有键的列表快照。"""
        return [k for k, _ in self.items()]
