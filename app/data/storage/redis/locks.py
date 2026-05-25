"""分布式锁 — Redis SET NX + 内存降级。"""

import asyncio
import logging
import uuid

logger = logging.getLogger(__name__)

# 内存锁降级（使用 asyncio.Lock）
_async_memory_locks: dict[str, asyncio.Lock] = {}
_memory_lock_owners: dict = {}


class DistributedLock:
    """分布式锁，优先 Redis，降级为进程内存锁。"""

    def __init__(self, lock_key: str, ttl: int = 30):
        self.lock_key = lock_key
        self.ttl = ttl
        self.owner_id = str(uuid.uuid4())
        self._redis_lock = None

    async def acquire(self) -> bool:
        """尝试获取锁。"""
        try:
            redis = None
            try:
                redis = __import__("app.data.storage.redis.client", fromlist=["get_redis"]).get_redis()
            except Exception:
                pass

            if redis:
                result = await redis.set(
                    self.lock_key, self.owner_id, nx=True, ex=self.ttl
                )
                return result is not None
        except Exception as e:
            logger.debug(f"Redis 锁获取失败，降级内存锁: {e}")

        # 内存降级：使用 asyncio.Lock 避免阻塞事件循环
        if self.lock_key not in _async_memory_locks:
            _async_memory_locks[self.lock_key] = asyncio.Lock()

        try:
            await asyncio.wait_for(
                _async_memory_locks[self.lock_key].acquire(),
                timeout=0.1,
            )
            _memory_lock_owners[self.lock_key] = self.owner_id
            return True
        except asyncio.TimeoutError:
            return False

    async def release(self) -> None:
        """释放锁。"""
        try:
            redis = None
            try:
                redis = __import__("app.data.storage.redis.client", fromlist=["get_redis"]).get_redis()
            except Exception:
                pass

            if redis:
                # Lua 脚本保证原子性：只释放自己持有的锁
                lua = "if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end"
                await redis.eval(lua, 1, self.lock_key, self.owner_id)
                return
        except Exception as e:
            logger.debug(f"Redis 锁释放失败: {e}")

        # 内存降级
        if self.lock_key in _async_memory_locks and _memory_lock_owners.get(self.lock_key) == self.owner_id:
            _async_memory_locks[self.lock_key].release()
            del _memory_lock_owners[self.lock_key]

    async def acquire_with_wait(self, max_wait: int = 30) -> bool:
        """带指数退避的获取锁，最多等待 max_wait 秒。"""
        delay = 0.1
        elapsed = 0.0
        while elapsed < max_wait:
            if await self.acquire():
                return True
            await asyncio.sleep(delay)
            elapsed += delay
            delay = min(delay * 1.5, 2.0)
        return False
