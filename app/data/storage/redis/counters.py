"""限流计数器 — 滑动窗口 + Token 哈希聚合。"""

import hashlib
import logging
import threading
import time
import uuid
from collections import defaultdict
from typing import Dict, Tuple

logger = logging.getLogger(__name__)

# 内存降级计数器
_memory_counters: Dict[str, list] = defaultdict(list)
# 内存计数器互斥锁：保证 try_increment 的"读+判断+写"原子性
# threading.Lock 在 asyncio 单线程模型下足够，且不需要 await 释放
_memory_counters_lock = threading.Lock()
# Token 哈希 → 数据源列表（配额聚合）
_token_hash_map: Dict[str, list] = defaultdict(list)


# Lua 脚本：原子地"清理过期 + 检查配额 + 写入 + 设置 TTL"
# 返回 [allowed(0/1), retry_after_seconds]
# allowed=1 表示本次请求占用配额成功；allowed=0 表示配额已满
# 注意：脚本接受 ZSET key、当前时间戳 now、cutoff 时间戳、唯一 member（避免覆盖）、
# 上限 limit、TTL expire_seconds
_LUA_TRY_INCREMENT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local cutoff = tonumber(ARGV[2])
local member = ARGV[3]
local limit = tonumber(ARGV[4])
local expire = tonumber(ARGV[5])

redis.call('ZREMRANGEBYSCORE', key, 0, cutoff)
local count = redis.call('ZCARD', key)
if count >= limit then
    -- 已超配额：不写入，告知调用方等待 60 秒（与默认窗口对齐）
    return {0, 60}
end
redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, expire)
return {1, 0}
"""


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
                # 函数内延迟导入：仅在需要时解析 Redis 客户端，避免模块加载期耦合。
                # client.py 不反向导入本模块，无循环依赖，可安全使用标准 import。
                from app.data.storage.redis.client import get_redis
                redis = get_redis()
            except Exception as e:
                logger.debug(f"获取 Redis 连接失败: {e}")

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
        with _memory_counters_lock:
            _memory_counters[key] = [t for t in _memory_counters[key] if t > cutoff]
            _memory_counters[key].append(now)
            return len(_memory_counters[key])

    async def get_count(self, key: str) -> int:
        """查询当前窗口计数（Redis 优先，失败降级内存）。

        与 increment 使用相同的滑动窗口语义，保证预检与递增看到同一个视图。
        """
        now = time.time()
        cutoff = now - self.window_seconds

        try:
            redis = None
            try:
                from app.data.storage.redis.client import get_redis
                redis = get_redis()
            except Exception as e:
                logger.debug(f"获取 Redis 连接失败: {e}")

            if redis:
                pipe = redis.pipeline()
                pipe.zremrangebyscore(key, 0, cutoff)
                pipe.zcard(key)
                pipe.expire(key, self.window_seconds * 2)
                results = await pipe.execute()
                return results[1]
        except Exception as e:
            logger.debug(f"Redis 计数器查询失败，降级内存: {e}")

        with _memory_counters_lock:
            _memory_counters[key] = [t for t in _memory_counters[key] if t > cutoff]
            return len(_memory_counters[key])

    async def try_increment(
        self, key: str, limit: int
    ) -> Tuple[bool, float]:
        """原子地"检查配额 + 递增"。

        替代旧实现 ``get_count`` + ``increment`` 两步操作，避免高并发下
        多个协程同时通过预检后递增导致超量。

        Args:
            key: Redis ZSET key
            limit: 配额上限（窗口内允许的请求数）

        Returns:
            (allowed, retry_after_seconds)：
            - allowed=True 表示本次请求已占用一份配额
            - allowed=False 表示配额已满，调用方应等待 retry_after_seconds
        """
        now = time.time()
        cutoff = now - self.window_seconds
        # member 必须唯一（同一 ms 内的并发请求不能用同一 score/member）
        # 使用 uuid4 保证跨 Python 实现/运行都可移植，避免依赖 CPython id 复用语义
        member = f"{now:.6f}_{uuid.uuid4().hex}"

        try:
            redis = None
            try:
                from app.data.storage.redis.client import get_redis
                redis = get_redis()
            except Exception as e:
                logger.debug(f"获取 Redis 连接失败: {e}")

            if redis:
                # 一次性执行"清理 + 计数 + 判断 + 写入 + TTL"，Redis 单线程模型保证原子性
                result = await redis.eval(
                    _LUA_TRY_INCREMENT,
                    1,
                    key,
                    str(now),
                    str(cutoff),
                    member,
                    int(limit),
                    self.window_seconds * 2,
                )
                # redis-py 在不同版本/配置下可能返回 bytes、int、list、tuple
                # 统一规范化为 Python 原生类型，避免 int(bytes) 抛 TypeError
                def _coerce(v):
                    if isinstance(v, bytes):
                        return v.decode("utf-8", errors="replace")
                    return v
                if isinstance(result, (list, tuple)):
                    allowed = bool(int(_coerce(result[0])))
                    retry = float(_coerce(result[1]) or 0)
                else:
                    allowed = bool(int(_coerce(result)))
                    retry = 0.0
                return allowed, retry
        except Exception as e:
            logger.debug(f"Redis try_increment 失败，降级内存: {e}")

        # 内存降级：用 _memory_counters_lock 保证原子性
        with _memory_counters_lock:
            _memory_counters[key] = [t for t in _memory_counters[key] if t > cutoff]
            current_list = _memory_counters[key]
            if len(current_list) >= limit:
                # 计算最早一条过期所需等待时间
                if current_list:
                    wait = current_list[0] + self.window_seconds - now
                else:
                    wait = 0.0
                return False, max(0.1, wait)
            current_list.append(now)
            return True, 0.0


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
