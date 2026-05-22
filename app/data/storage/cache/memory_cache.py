"""TTL 内存缓存 — 用于配置、能力表等 30s 缓存。"""

import threading
import time
from typing import Any, Dict, Optional


class TTLCache:
    """线程安全的 TTL 内存缓存。"""

    def __init__(self, default_ttl: int = 30):
        self.default_ttl = default_ttl
        self._store: Dict[str, tuple] = {}  # key → (value, expire_time)
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key in self._store:
                value, expire_time = self._store[key]
                if time.time() < expire_time:
                    return value
                del self._store[key]
        return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        ttl = ttl if ttl is not None else self.default_ttl
        with self._lock:
            self._store[key] = (value, time.time() + ttl)

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def invalidate_pattern(self, prefix: str) -> None:
        with self._lock:
            keys_to_remove = [k for k in self._store if k.startswith(prefix)]
            for k in keys_to_remove:
                del self._store[k]

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._store)
