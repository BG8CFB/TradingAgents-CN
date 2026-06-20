"""分布式锁 — Redis SET NX + 内存降级。"""

import asyncio
import logging
import uuid
from collections import OrderedDict
from typing import Optional

logger = logging.getLogger(__name__)

# 内存锁降级（使用 asyncio.Lock）
# 使用 OrderedDict + LRU 上限，避免长跑后 _async_memory_locks 无限增长
_MEMORY_LOCK_MAX_ENTRIES = 1000
# 单次 LRU 扫描淘汰上限，避免长跑后 O(N) 阻塞事件循环
_MEMORY_LOCK_EVICT_BATCH = 100
_async_memory_locks: "OrderedDict[str, asyncio.Lock]" = OrderedDict()
# key -> owner_id（用于 TTL 回调校验持锁身份）
_memory_lock_owners: dict = {}
# key -> TimerHandle（用于显式 release 时取消未触发的 TTL 回调，避免内存泄漏）
_memory_lock_timers: dict = {}


def _evict_memory_locks_if_full() -> None:
    """LRU 淘汰：当 lock 字典超过上限时，清理最早未使用的项。

    只清理当前未被持锁的（避免误清理活跃锁）。
    单次扫描上限 ``_MEMORY_LOCK_EVICT_BATCH`` 次，防止长跑后字典过大导致 O(N) 阻塞。
    剩余未清理项留待下次调用。
    """
    scanned = 0
    while (
        len(_async_memory_locks) > _MEMORY_LOCK_MAX_ENTRIES
        and scanned < _MEMORY_LOCK_EVICT_BATCH
    ):
        scanned += 1
        try:
            key, lock = next(iter(_async_memory_locks.items()))
        except StopIteration:
            return
        # 已释放的锁才能淘汰
        if not lock.locked():
            _async_memory_locks.pop(key, None)
            _memory_lock_owners.pop(key, None)
            timer = _memory_lock_timers.pop(key, None)
            if timer is not None:
                try:
                    timer.cancel()
                except Exception:
                    pass
        else:
            # 把它移到末尾，下次再淘汰
            _async_memory_locks.move_to_end(key)
            # 如果整个字典全部都是 locked，跳出避免死循环
            if all(lk.locked() for lk in _async_memory_locks.values()):
                return


class DistributedLock:
    """分布式锁，优先 Redis，降级为进程内存锁。"""

    def __init__(self, lock_key: str, ttl: int = 30):
        self.lock_key = lock_key
        self.ttl = ttl
        self.owner_id = str(uuid.uuid4())
        self._redis_lock = None
        # 关键修复：保存自己的 TimerHandle 引用，release 时显式 cancel
        # 避免 TimerHandle 在事件循环 callback 队列中堆积导致内存泄漏
        self._timer_handle: Optional[asyncio.TimerHandle] = None

    async def acquire(self) -> bool:
        """尝试获取锁。"""
        try:
            from app.data.storage.redis.client import get_redis
            redis = None
            try:
                redis = get_redis()
            except Exception as e:
                logger.debug(f"获取 Redis 连接失败: {e}")

            if redis:
                result = await redis.set(
                    self.lock_key, self.owner_id, nx=True, ex=self.ttl
                )
                return result is not None
        except Exception as e:
            logger.debug(f"Redis 锁获取失败，降级内存锁: {e}")

        # 内存降级：使用 asyncio.Lock 避免阻塞事件循环
        # 关键原子性修复：用 setdefault 替代 "in / assign" 两步操作，避免并发首登时
        # 两个协程同时进入 if-not-in 分支各自创建新 Lock，最终互相覆盖丢失一个
        _evict_memory_locks_if_full()
        # setdefault：key 已存在则返回已有 Lock，否则创建新 Lock 并写入；
        # CPython 中 dict.setdefault 是 C 层原子调用，无需额外加锁
        lock_obj = _async_memory_locks.setdefault(self.lock_key, asyncio.Lock())
        # 无论新建还是命中已存在，都移到末尾标记为最近使用（LRU 顺序维护）
        _async_memory_locks.move_to_end(self.lock_key)

        try:
            await asyncio.wait_for(
                lock_obj.acquire(),
                timeout=0.1,
            )
            _memory_lock_owners[self.lock_key] = self.owner_id
            # 设置 TTL 自动释放，防止持锁协程异常退出导致死锁
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.get_event_loop()
            # 关键修复：TTL 回调必须验证 owner_id，防止释放+重新获取场景中错误释放新锁
            def _ttl_release(owner_id: str = self.owner_id) -> None:
                lock_obj = _async_memory_locks.get(self.lock_key)
                current_owner = _memory_lock_owners.get(self.lock_key)
                if (
                    lock_obj is not None
                    and lock_obj.locked()
                    and current_owner == owner_id
                ):
                    try:
                        lock_obj.release()
                    except RuntimeError:
                        # 锁可能已被 release() 显式释放
                        pass
                    _memory_lock_owners.pop(self.lock_key, None)
                    _async_memory_locks.pop(self.lock_key, None)
                # 清理 timer 索引（无论是否触发了释放）
                _memory_lock_timers.pop(self.lock_key, None)
            # 保存 TimerHandle 引用，便于 release 时显式 cancel
            self._timer_handle = loop.call_later(self.ttl, _ttl_release)
            _memory_lock_timers[self.lock_key] = self._timer_handle
            return True
        except asyncio.TimeoutError:
            return False

    async def release(self) -> None:
        """释放锁。"""
        # 关键修复：先取消未触发的 TTL 回调，避免 TimerHandle 泄漏
        if self._timer_handle is not None:
            try:
                self._timer_handle.cancel()
            except Exception:
                pass
            self._timer_handle = None
            _memory_lock_timers.pop(self.lock_key, None)

        try:
            from app.data.storage.redis.client import get_redis
            redis = None
            try:
                redis = get_redis()
            except Exception as e:
                logger.debug(f"获取 Redis 连接失败: {e}")

            if redis:
                # Lua 脚本保证原子性：只释放自己持有的锁
                lua = "if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end"
                await redis.eval(lua, 1, self.lock_key, self.owner_id)
                return
        except Exception as e:
            logger.debug(f"Redis 锁释放失败: {e}")

        # 内存降级：release 时同时清理 owners 和 locks（修复内存泄漏）
        lock_obj = _async_memory_locks.get(self.lock_key)
        if lock_obj is not None and _memory_lock_owners.get(self.lock_key) == self.owner_id:
            try:
                lock_obj.release()
            except RuntimeError:
                # 锁可能已被 TTL 回调释放
                pass
            _memory_lock_owners.pop(self.lock_key, None)
            # 关键修复：从 _async_memory_locks 中也删除，避免 dict 无限增长
            _async_memory_locks.pop(self.lock_key, None)
        else:
            # owner 不匹配：记 warning 而非静默，便于排查"重复 release"或"TTL 已触发"问题
            logger.warning(
                "DistributedLock.release: owner 不匹配，跳过释放 key=%s "
                "expected=%s current=%s",
                self.lock_key,
                self.owner_id,
                _memory_lock_owners.get(self.lock_key),
            )

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
