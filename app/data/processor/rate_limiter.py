"""限流器 — 滑动窗口计数 + Token 感知分桶 + 日配额 + Redis 故障熔断降级。

设计目标：

- 正常情况下走 Redis 滑动窗口计数（多 worker 共享配额）
- Redis 连续失败时熔断式切换到内存计数（fail-open），避免单点故障
  拖死所有数据同步任务（原 fail-closed 实现会让全平台限流瘫痪 ≥30s）
- 内存计数采用 60s 滑动窗口（deque），单 worker 内的兜底配额
- Redis 恢复后自动切回（每 10s 探测一次）
- ``asyncio.Lock`` 惰性创建绑定到 running loop，避免跨 loop 重用

Token 感知分桶（Phase 2）：

- 配置了 Token 的源（如 tushare/tushare_hk/tushare_us）按
  ``ratelimit:{sha256(token)[:8]}`` 分桶 —— 同一 Token 的多市场共享
  配额（Tushare 的频次/积分按账号计，而非按接口别名计）
- 未配置 Token 的源按 ``ratelimit:{source}`` 分桶（原行为）
- Token 经 ds_key_utils 解析（DB 优先 + ENV 回退），带 TTL 缓存，
  也可由调用方通过 acquire(token=...) 显式传入
- ``rate_per_day`` 日配额：Redis INCR 日计数（key 带日期，EXPIRE 48h），
  超额拒绝并记日志；内存降级路径用进程内计数
"""

from __future__ import annotations

import asyncio
import collections
import hashlib
import logging
import time
from datetime import datetime, timedelta
from typing import Deque, Dict, Optional, Tuple

from app.data.storage.redis.counters import SlidingWindowCounter

logger = logging.getLogger(__name__)

# 触发熔断的连续失败次数
_FAIL_OPEN_THRESHOLD = 3
# 熔断后探测 Redis 恢复的间隔（秒）
_PROBE_INTERVAL = 10.0
# Redis 故障期间短暂退避（秒），避免打爆重连
_REDIS_DOWN_BACKOFF = 5.0
# Token 解析缓存 TTL（秒）：Token 配置变更最迟 5 分钟生效
_TOKEN_CACHE_TTL = 300.0
# 日配额 Redis key 前缀（与分钟级滑动窗口 key 区分）
_DAILY_KEY_PREFIX = "ratelimit_day"


def _bucket_key(source: str, token: Optional[str]) -> str:
    """Token 感知分桶键。

    有 Token：``ratelimit:{sha256(token)[:8]}``（同 Token 跨市场/跨源共享桶，
    不回显 Token 明文）；无 Token：``ratelimit:{source}``。
    """
    if token:
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:8]
        return f"ratelimit:{digest}"
    return f"ratelimit:{source}"


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
        # 内存日配额兜底：bucket:date -> count
        self._memory_daily: Dict[str, int] = {}
        # Token 解析缓存：source -> (token, resolved_at)
        self._token_cache: Dict[str, Tuple[Optional[str], float]] = {}

    def configure(self, source: str, rate_per_minute: int = 60, **kwargs) -> None:
        self._limits[source] = {
            "rate_per_minute": rate_per_minute,
            "rate_per_day": kwargs.get("rate_per_day"),
            "last_request_time": 0,
            "polite_interval_ms": kwargs.get("polite_interval_ms", 1000),
        }
        if source not in self._counters:
            self._counters[source] = SlidingWindowCounter(window_seconds=60)

    # ── Token 解析 ──────────────────────────────────────────

    async def _resolve_token(self, source: str, token: Optional[str]) -> Optional[str]:
        """解析源 Token：显式传入优先，其次 ds_key_utils（带 TTL 缓存）。"""
        if token is not None:
            return token or None
        cached = self._token_cache.get(source)
        now = time.time()
        if cached is not None and now - cached[1] < _TOKEN_CACHE_TTL:
            return cached[0]
        try:
            from app.utils.ds_key_utils import get_datasource_api_key

            resolved = await asyncio.to_thread(get_datasource_api_key, source)
        except Exception as exc:
            logger.debug(f"[ratelimit] 解析 {source} Token 失败: {exc}")
            resolved = None
        self._token_cache[source] = (resolved, now)
        return resolved

    # ── 锁管理 ──────────────────────────────────────────────

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

    # ── 日配额 ──────────────────────────────────────────────

    async def _daily_quota_check(self, source: str, bucket: str, rate_per_day: int) -> Tuple[bool, float]:
        """日配额检查 + 占用（Redis INCR 优先，失败降级内存计数）。

        Returns:
            (是否允许, 超额时需等待秒数)
        """
        now = datetime.now()
        day = now.strftime("%Y%m%d")
        key = f"{_DAILY_KEY_PREFIX}:{bucket}:{day}"
        try:
            from app.data.storage.redis.client import get_redis

            redis = get_redis()
            count = await redis.incr(key)
            if count == 1:
                # 首次计数设置 48h 过期（跨两天窗口，避免残留）
                await redis.expire(key, 48 * 3600)
        except Exception as exc:
            # Redis 故障：降级为进程内日计数（fail-open，不阻塞业务）
            logger.debug(f"[ratelimit] 日配额 Redis 计数失败，降级内存: {exc}")
            count = self._memory_daily.get(key, 0) + 1
            self._memory_daily[key] = count

        if count > rate_per_day:
            wait = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0) - now
            logger.warning(
                "[ratelimit] 源 %s 日配额触顶: %d/%d（bucket=%s），拒绝请求至次日零点",
                source,
                rate_per_day,
                count - 1,
                bucket,
            )
            return False, max(1.0, wait.total_seconds())
        return True, 0

    # ── 配额获取 ────────────────────────────────────────────

    async def acquire(self, source: str, domain: str = "", token: Optional[str] = None) -> Tuple[bool, float]:
        """尝试获取请求配额。Returns (是否允许, 需等待秒数)。

        Args:
            source: 数据源名（配置与日志定位用）。
            domain: 数据域（仅用于日志）。
            token: 可选显式 Token；未提供时按 source 经 ds_key_utils 解析。
                同一 Token 的多个源共享分钟级/日级配额桶。

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
            need_probe = fail_open and (time.time() - self._last_probe_time >= _PROBE_INTERVAL)
            if need_probe:
                self._last_probe_time = time.time()

        if fail_open:
            # 熔断中：先尝试探测恢复，未到探测时间则用内存计数
            if need_probe:
                recovered = await self._probe_redis(source)
                if recovered:
                    async with state_lock:
                        logger.info(f"[ratelimit] Redis 已恢复，从 fail-open 切回正常路径 source={source}")
                        self._fail_open_mode = False
                        self._redis_fail_count = 0
                else:
                    return await self._memory_acquire(source, limits, token)
            else:
                return await self._memory_acquire(source, limits, token)

        # 正常路径：Redis 计数（高并发可重叠 I/O）
        # 原子性修复：用 try_increment 一次性完成"清理 + 计数 + 判断 + 写入"，
        # 避免 get_count + increment 两步之间被并发请求穿透配额
        bucket = _bucket_key(source, await self._resolve_token(source, token))
        counter = self._counters.get(source)
        if counter:
            try:
                allowed, retry = await counter.try_increment(
                    bucket,
                    limits["rate_per_minute"],
                )
                if allowed:
                    async with state_lock:
                        self._redis_fail_count = 0
                    # 分钟级配额通过后占用日配额（若配置）
                    rate_per_day = limits.get("rate_per_day")
                    if rate_per_day:
                        day_ok, day_wait = await self._daily_quota_check(source, bucket, int(rate_per_day))
                        if not day_ok:
                            return False, day_wait
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
                        return await self._memory_acquire(source, limits, token)
                # 未到阈值：短暂退避（与原 fail-closed 语义兼容），给 Redis 恢复机会
                logger.warning(
                    f"[ratelimit] Redis 临时故障 {fail_count}/{_FAIL_OPEN_THRESHOLD} "
                    f"source={source}/{domain}: {type(exc).__name__}: {exc}"
                )
                return False, _REDIS_DOWN_BACKOFF

        return True, 0

    async def _memory_acquire(self, source: str, limits: dict, token: Optional[str] = None) -> Tuple[bool, float]:
        """内存滑动窗口兜底：仅在 fail-open 模式下生效。

        - 60s 滑动窗口（deque maxlen=rate_per_minute）
        - 清理过期记录；窗口未满则允许
        - 配置了日配额的源同时做进程内日计数
        """
        rate = limits["rate_per_minute"]
        window = 60.0
        now = time.time()
        cutoff = now - window

        bucket = _bucket_key(source, await self._resolve_token(source, token))
        deque_ = self._memory_counters.get(bucket)
        if deque_ is None:
            deque_ = collections.deque(maxlen=max(1, rate))
            self._memory_counters[bucket] = deque_

        # 清理过期记录（deque 严格 FIFO，所以从左端 pop 即可）
        while deque_ and deque_[0] < cutoff:
            deque_.popleft()

        if len(deque_) >= rate:
            # 计算最早一条过期所需等待时间
            wait = deque_[0] + window - now
            return False, max(0.1, wait)

        deque_.append(now)

        rate_per_day = limits.get("rate_per_day")
        if rate_per_day:
            day = datetime.now().strftime("%Y%m%d")
            key = f"{_DAILY_KEY_PREFIX}:{bucket}:{day}"
            count = self._memory_daily.get(key, 0) + 1
            self._memory_daily[key] = count
            if count > int(rate_per_day):
                logger.warning(
                    "[ratelimit] 源 %s 日配额触顶（内存兜底）: %d（bucket=%s）",
                    source,
                    int(rate_per_day),
                    bucket,
                )
                return False, 60.0
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
        self, source: str, domain: str = "", max_wait: float = 30, token: Optional[str] = None
    ) -> bool:
        start = time.time()
        while time.time() - start < max_wait:
            allowed, wait = await self.acquire(source, domain, token=token)
            if allowed:
                return True
            await asyncio.sleep(min(wait, 1.0))
        return False

    async def release(self, source: str, domain: str = "", token: Optional[str] = None) -> bool:
        """归还最近一次 ``acquire`` 扣减的配额。

        使用场景：调用方成功 acquire 后，因为熔断/前置校验失败而没有真正发起
        请求，此时应归还配额，避免熔断期间白白消耗 rate_limiter 令牌。

        Returns:
            True 表示成功归还；False 表示当前没有可归还的计数器（如 fail-open 模式下
            使用内存 deque，或在 Redis 路径上 try_decrement 失败）。
        """
        limits = self._limits.get(source)
        if not limits:
            return False

        # fail-open 模式：从内存 deque 右端弹出最近一条（仅当最后一条属于本次窗口）
        state_lock = self._ensure_state_lock()
        async with state_lock:
            fail_open = self._fail_open_mode

        bucket = _bucket_key(source, await self._resolve_token(source, token))

        if fail_open:
            deque_ = self._memory_counters.get(bucket)
            if deque_:
                try:
                    deque_.pop()
                    return True
                except IndexError:
                    return False
            return False

        # 正常路径：通知 Redis 计数器回退一次
        counter = self._counters.get(source)
        if not counter:
            return False
        try:
            return await counter.try_decrement(bucket)
        except Exception as exc:
            logger.debug(f"[ratelimit] release 失败 source={source}/{domain}: {exc}")
            return False
