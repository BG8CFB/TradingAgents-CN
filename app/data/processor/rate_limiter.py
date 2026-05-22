"""限流器 — 滑动窗口计数。"""

import asyncio
import logging
import time
from typing import Dict, Tuple

from app.data.storage.redis.counters import SlidingWindowCounter

logger = logging.getLogger(__name__)


class RateLimiter:
    """限流器，按数据源配置不同的限流参数。"""

    def __init__(self):
        self._counters: Dict[str, SlidingWindowCounter] = {}
        self._limits: Dict[str, dict] = {}

    def configure(self, source: str, rate_per_minute: int = 60, **kwargs) -> None:
        self._limits[source] = {
            "rate_per_minute": rate_per_minute,
            "last_request_time": 0,
            "polite_interval_ms": kwargs.get("polite_interval_ms", 1000),
        }
        if source not in self._counters:
            self._counters[source] = SlidingWindowCounter(window_seconds=60)

    async def acquire(self, source: str, domain: str = "") -> Tuple[bool, float]:
        """尝试获取请求配额。Returns (是否允许, 需等待秒数)。"""
        limits = self._limits.get(source)
        if not limits:
            return True, 0

        interval_s = limits.get("polite_interval_ms", 1000) / 1000
        elapsed = time.time() - limits.get("last_request_time", 0)
        if elapsed < interval_s:
            return False, interval_s - elapsed

        counter = self._counters.get(source)
        if counter:
            count = await counter.increment(f"ratelimit:{source}")
            if count > limits["rate_per_minute"]:
                return False, 60

        limits["last_request_time"] = time.time()
        return True, 0

    async def wait_and_acquire(self, source: str, domain: str = "", max_wait: float = 30) -> bool:
        start = time.time()
        while time.time() - start < max_wait:
            allowed, wait = await self.acquire(source, domain)
            if allowed:
                return True
            await asyncio.sleep(min(wait, 1.0))
        return False
