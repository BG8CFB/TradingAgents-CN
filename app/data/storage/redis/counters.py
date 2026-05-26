"""限流计数器 — 滑动窗口 + Token 哈希聚合。"""

import hashlib
import logging
import time
from collections import defaultdict
from typing import Dict

logger = logging.getLogger(__name__)

# 内存降级计数器
_memory_counters: Dict[str, list] = defaultdict(list)
# Token 哈希 → 数据源列表（配额聚合）
_token_hash_map: Dict[str, list] = defaultdict(list)


class SlidingWindowCounter:
    """滑动窗口计数器。"""

    def __init__(self, window_seconds: int = 60):
        self.window_seconds = window_seconds

    async def increment(self, key: str) -> int:
        """递增并返回当前窗口计数。"""
        now = time.time()
        cutoff = now - self.window_seconds

        try:
            redis = None
            try:
                # 使用 __import__ 避免模块级别循环导入，运行时按需获取 Redis 客户端
                redis = __import__("app.data.storage.redis.client", fromlist=["get_redis"]).get_redis()
            except Exception:
                pass

            if redis:
                pipe = redis.pipeline()
                pipe.zadd(key, {str(now): now})
                pipe.zremrangebyscore(key, 0, cutoff)
                pipe.zcard(key)
                pipe.expire(key, self.window_seconds * 2)
                results = await pipe.execute()
                return results[2]
        except Exception as e:
            logger.debug(f"Redis 计数器失败，降级内存: {e}")

        # 内存降级
        _memory_counters[key] = [t for t in _memory_counters[key] if t > cutoff]
        _memory_counters[key].append(now)
        return len(_memory_counters[key])

    async def get_count(self, key: str) -> int:
        now = time.time()
        cutoff = now - self.window_seconds
        _memory_counters[key] = [t for t in _memory_counters[key] if t > cutoff]
        return len(_memory_counters[key])


class RateLimiterQuota:
    """Tushare Token 哈希配额聚合。"""

    @staticmethod
    def register_token(source: str, token: str) -> str:
        """注册数据源的 Token，返回哈希 key。"""
        token_hash = hashlib.sha256(token.encode()).hexdigest()[:8]
        _token_hash_map[token_hash].append(source)
        return token_hash

    @staticmethod
    def get_sources_by_token_hash(token_hash: str) -> list:
        return _token_hash_map.get(token_hash, [])

    @staticmethod
    def clear():
        _token_hash_map.clear()
