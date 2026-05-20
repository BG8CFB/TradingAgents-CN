"""
限流器 (Rate Limiter)

滑动窗口计数器，控制各数据源的请求频率。
Redis 优先（INCR + EXPIRE），不可用时降级为进程内存 deque。
"""

import logging
import time
from collections import deque
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class _InMemoryCounter:
    """进程内存滑动窗口计数器"""

    __slots__ = ("window_seconds", "_timestamps")

    def __init__(self, window_seconds: float):
        self.window_seconds = window_seconds
        self._timestamps: deque = deque()

    def count_and_add(self) -> int:
        """添加当前时间戳并返回窗口内请求数"""
        now = time.monotonic()
        cutoff = now - self.window_seconds

        # 清理过期时间戳
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()

        self._timestamps.append(now)
        return len(self._timestamps)


class RateLimiter:
    """
    限流管理器

    粒度: (source, api_name) 组合。
    Redis 优先（INCR + EXPIRE），不可用时降级为进程内存 deque。
    """

    def __init__(
        self,
        window_seconds: float = 60.0,
        tushare_limit: int = 200,
        akshare_min_interval: float = 0.5,
        baostock_per_session: int = 50,
        redis_client=None,
    ):
        self._window_seconds = window_seconds
        self._tushare_limit = tushare_limit
        self._akshare_min_interval = akshare_min_interval
        self._baostock_per_session = baostock_per_session
        self._counters: Dict[Tuple[str, str], _InMemoryCounter] = {}
        self._last_call_time: Dict[str, float] = {}
        self._redis = redis_client
        self._redis_prefix = "rl:"

    def _source_limit(self, source: str) -> int:
        """获取数据源的窗口期请求上限"""
        limits = {
            "tushare": self._tushare_limit,
            "akshare": int(self._window_seconds / self._akshare_min_interval),
            "baostock": self._baostock_per_session,
        }
        return limits.get(source, 120)  # 默认 120 次/分钟

    def _get_counter(self, source: str, api_name: str) -> _InMemoryCounter:
        key = (source, api_name)
        if key not in self._counters:
            self._counters[key] = _InMemoryCounter(self._window_seconds)
        return self._counters[key]

    async def acquire(self, source: str, api_name: str = "default") -> Tuple[bool, float]:
        """
        尝试获取请求许可。

        Returns:
            (allowed, wait_seconds): 是否允许请求，以及需要等待的秒数（如不允许）
        """
        limit = self._source_limit(source)

        # 优先尝试 Redis
        if self._redis is not None:
            allowed, wait = await self._redis_acquire(source, api_name, limit)
            if allowed is not None:
                return allowed, wait

        # 降级到内存计数器
        counter = self._get_counter(source, api_name)

        current_count = counter.count_and_add()
        if current_count <= limit:
            # 额外检查 AKShare 的礼貌间隔
            if source == "akshare":
                now = time.monotonic()
                last = self._last_call_time.get(source, 0)
                elapsed = now - last
                if elapsed < self._akshare_min_interval:
                    wait = self._akshare_min_interval - elapsed
                    return False, wait
                self._last_call_time[source] = now

            return True, 0.0

        # 计算需要等待的时间
        wait = self._window_seconds / limit
        return False, wait

    async def _redis_acquire(
        self, source: str, api_name: str, limit: int,
    ) -> Tuple[Optional[bool], float]:
        """
        Redis 滑动窗口限流（INCR + EXPIRE 模式）。
        返回 (None, 0) 表示 Redis 不可用，需要降级。
        """
        try:
            import time as _time
            key = f"{self._redis_prefix}{source}:{api_name}"
            pipe = self._redis.pipeline()
            now_ts = _time.time()
            window_start = now_ts - self._window_seconds

            # 移除窗口外的记录
            pipe.zremrangebyscore(key, "-inf", window_start)
            # 添加当前请求
            pipe.zadd(key, {str(now_ts): now_ts})
            # 设置过期
            pipe.expire(key, int(self._window_seconds) + 1)
            # 获取窗口内数量
            pipe.zcard(key)

            results = await pipe.execute()
            current_count = results[-1]

            if current_count <= limit:
                return True, 0.0

            wait = self._window_seconds / limit
            return False, wait
        except Exception as e:
            logger.debug("Redis 限流失败（降级为内存）: %s", e)
            return None, 0.0

    def get_usage(self, source: str, api_name: str = "default") -> Dict:
        """获取当前使用情况"""
        key = (source, api_name)
        counter = self._counters.get(key)
        limit = self._source_limit(source)
        return {
            "source": source,
            "api_name": api_name,
            "current_count": len(counter._timestamps) if counter else 0,
            "limit": limit,
            "window_seconds": self._window_seconds,
        }
