"""限流器 — 滑动窗口计数 + Redis 故障熔断降级。

设计目标：

- 正常情况下走 Redis 滑动窗口计数（多 worker 共享配额）
- Redis 连续失败时熔断式切换到内存计数（fail-open），避免单点故障
  拖死所有数据同步任务（原 fail-closed 实现会让全平台限流瘫痪 ≥30s）
- 内存计数采用 60s 滑动窗口（deque），单 worker 内的兜底配额
- Redis 恢复后自动切回（每 10s 探测一次）
- ``asyncio.Lock`` 惰性创建绑定到 running loop，避免跨 loop 重用
"""

from __future__ import annotations

import asyncio
import collections
import logging
import time
from typing import Deque, Dict, Optional, Tuple

from app.data.storage.redis.counters import SlidingWindowCounter

logger = logging.getLogger(__name__)

# 触发熔断的连续失败次数
_FAIL_OPEN_THRESHOLD = 3
# 熔断后探测 Redis 恢复的间隔（秒）
_PROBE_INTERVAL = 10.0
# Redis 故障期间短暂退避（秒），避免打爆重连
_REDIS_DOWN_BACKOFF = 5.0


class RateLimiter:
    """限流器，按数据源配置不同的限流参数。"""

    def __init__(self):
        self._counters: Dict[str, SlidingWindowCounter] = {}
        self._limits: Dict[str, dict] = {}
        # 跨 loop 安全：lock 惰性创建绑定到首次 acquire 的 loop
        self._locks: Dict[str, asyncio.Lock] = {}
        self._lock_loop: Optional[asyncio.AbstractEventLoop] = None
        # 全局状态锁：保护 _redis_fail_count / _fail_open_mode / _last_probe_time
        # 这些状态跨所有 source 共享，per-source lock 无法保护；单独的 state_lock
        # 只包裹纯内存读写，不包裹 Redis I/O，避免串行化。
        self._state_lock: Optional[asyncio.Lock] = None
        # Redis 熔断状态
        self._redis_fail_count = 0
        self._fail_open_mode = False
        self._last_probe_time = 0.0
        # 内存计数兜底（仅在 fail-open 模式下使用）
        self._memory_counters: Dict[str, Deque[float]] = {}

    def configure(self, source: str, rate_per_minute: int = 60, **kwargs) -> None:
        self._limits[source] = {
            "rate_per_minute": rate_per_minute,
            "last_request_time": 0,
            "polite_interval_ms": kwargs.get("polite_interval_ms", 1000),
        }
        if source not in self._counters:
            self._counters[source] = SlidingWindowCounter(window_seconds=60)

    def _ensure_lock(self, source: str) -> asyncio.Lock:
        """惰性创建 asyncio.Lock，绑定到当前 running loop。

        解决原实现 ``configure`` 阶段同步创建 Lock 可能绑定到错误 loop 的问题：
        - ``configure`` 通常在 startup（主 loop 还未运行）调用
        - ``acquire`` 在 worker loop 中执行；如果 loop 不一致，Lock 会抛
          ``got Future attached to a different loop``
        """
        current_loop = asyncio.get_running_loop()
        if self._lock_loop is not current_loop:
            # loop 切换（罕见但需防御）：旧 Lock 已无效，全部丢弃重建
            self._locks.clear()
            self._state_lock = None
            self._lock_loop = current_loop
        if source not in self._locks:
            self._locks[source] = asyncio.Lock()
        return self._locks[source]

    def _ensure_state_lock(self) -> asyncio.Lock:
        """惰性创建保护全局熔断状态的锁，与 _ensure_lock 同 loop 绑定。"""
        if self._state_lock is None:
            self._state_lock = asyncio.Lock()
        return self._state_lock

    async def acquire(self, source: str, domain: str = "") -> Tuple[bool, float]:
        """尝试获取请求配额。Returns (是否允许, 需等待秒数)。

        性能要点：
        - 仅 ``last_request_time`` 检查/更新在锁内（O(1) 内存读写）
        - Redis 计数器递增在锁外执行，避免同源请求被串行化
        - 极短临界区允许高并发；polite_interval 由锁内时间戳保证，不会绕过
        - Redis 持续故障时自动切换到内存计数（fail-open），不阻塞业务
        """
        limits = self._limits.get(source)
        if not limits:
            return True, 0

        lock = self._ensure_lock(source)

        # 第一步：锁内只做 polite_interval 检查 + 时间戳更新（纯内存）
        async with lock:
            interval_s = limits.get("polite_interval_ms", 1000) / 1000
            elapsed = time.time() - limits.get("last_request_time", 0)
            if elapsed < interval_s:
                return False, interval_s - elapsed
            # 提前更新时间戳，让后续请求在 polite_interval 内立即被拒
            limits["last_request_time"] = time.time()

        # 第二步：根据 Redis 健康状态选择计数路径
        # 全局熔断状态读写用 state_lock 保护，避免并发下 fail_count 丢失或
        # fail_open_mode 被多个协程同时切换。锁只包裹纯内存读写，不包裹 Redis I/O。
        state_lock = self._ensure_state_lock()
        async with state_lock:
            fail_open = self._fail_open_mode
            need_probe = fail_open and (
                time.time() - self._last_probe_time >= _PROBE_INTERVAL
            )
            if need_probe:
                self._last_probe_time = time.time()

        if fail_open:
            # 熔断中：先尝试探测恢复，未到探测时间则用内存计数
            if need_probe:
                recovered = await self._probe_redis(source)
                if recovered:
                    async with state_lock:
                        logger.info(
                            "[ratelimit] Redis 已恢复，从 fail-open 切回正常路径 "
                            f"source={source}"
                        )
                        self._fail_open_mode = False
                        self._redis_fail_count = 0
                else:
                    return self._memory_acquire(source, limits)
            else:
                return self._memory_acquire(source, limits)

        # 正常路径：Redis 计数（高并发可重叠 I/O）
        # 原子性修复：用 try_increment 一次性完成"清理 + 计数 + 判断 + 写入"，
        # 避免 get_count + increment 两步之间被并发请求穿透配额
        counter = self._counters.get(source)
        if counter:
            try:
                allowed, retry = await counter.try_increment(
                    f"ratelimit:{source}",
                    limits["rate_per_minute"],
                )
                if allowed:
                    async with state_lock:
                        self._redis_fail_count = 0
                    return True, 0
                return False, retry
            except Exception as exc:
                # Redis 故障：累加失败计数；达阈值切 fail-open
                async with state_lock:
                    self._redis_fail_count += 1
                    fail_count = self._redis_fail_count
                    if fail_count >= _FAIL_OPEN_THRESHOLD:
                        self._fail_open_mode = True
                        self._last_probe_time = time.time()
                        logger.warning(
                            f"[ratelimit] Redis 连续失败 {fail_count} 次，"
                            f"切换到 fail-open 内存计数 source={source}/{domain}: "
                            f"{type(exc).__name__}: {exc}"
                        )
                        # 切换瞬间立刻走内存路径，不让这次请求卡在退避
                        return self._memory_acquire(source, limits)
                # 未到阈值：短暂退避（与原 fail-closed 语义兼容），给 Redis 恢复机会
                logger.warning(
                    f"[ratelimit] Redis 临时故障 {fail_count}/{_FAIL_OPEN_THRESHOLD} "
                    f"source={source}/{domain}: {type(exc).__name__}: {exc}"
                )
                return False, _REDIS_DOWN_BACKOFF

        return True, 0

    def _memory_acquire(self, source: str, limits: dict) -> Tuple[bool, float]:
        """内存滑动窗口兜底：仅在 fail-open 模式下生效。

        - 60s 滑动窗口（deque maxlen=rate_per_minute）
        - 清理过期记录；窗口未满则允许
        """
        rate = limits["rate_per_minute"]
        window = 60.0
        now = time.time()
        cutoff = now - window

        deque_ = self._memory_counters.get(source)
        if deque_ is None:
            deque_ = collections.deque(maxlen=max(1, rate))
            self._memory_counters[source] = deque_

        # 清理过期记录（deque 严格 FIFO，所以从左端 pop 即可）
        while deque_ and deque_[0] < cutoff:
            deque_.popleft()

        if len(deque_) >= rate:
            # 计算最早一条过期所需等待时间
            wait = deque_[0] + window - now
            return False, max(0.1, wait)

        deque_.append(now)
        return True, 0

    async def _probe_redis(self, source: str) -> bool:
        """探测 Redis 是否恢复。成功返回 True。"""
        counter = self._counters.get(source)
        if not counter:
            return False
        try:
            await counter.get_count(f"ratelimit:{source}")
            return True
        except Exception:
            return False

    async def wait_and_acquire(
        self, source: str, domain: str = "", max_wait: float = 30
    ) -> bool:
        start = time.time()
        while time.time() - start < max_wait:
            allowed, wait = await self.acquire(source, domain)
            if allowed:
                return True
            await asyncio.sleep(min(wait, 1.0))
        return False
