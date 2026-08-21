"""模型级并发限流器（进程内、跨事件循环安全）

语义：每个模型（按 ``provider|model_name`` 键）持有一个 FIFO 信号量，
限制该模型**同时在途**的 LLM 请求数。槽位是灵活占位：

- 仅在请求执行期间持有槽位，请求结束立即释放给等待者
- 排队等待不占槽位（如辩论 barrier 间隙）
- 单任务自动拿满可用额度；批量任务在同一进程内运行时公平争抢

为什么不用 ``asyncio.Semaphore``：每个分析任务在工作线程中
``asyncio.run()`` 跑独立事件循环（runtime.propagate_sync），
``asyncio.Semaphore`` 绑定创建时的 loop，跨任务共享会失效。
本模块用 ``threading`` 原语实现，async 侧经专用线程池桥接等待。

边界：Worker 为独立进程，各进程各持全额额度（与 gunicorn per-worker
限流同构）；跨进程精确限额需 Redis 租约信号量，列为后续扩展。
"""

import asyncio
import logging
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# 等待者阻塞专用线程（不占 asyncio 默认 executor）；上限覆盖并发等待场景
_WAIT_POOL = ThreadPoolExecutor(max_workers=32, thread_name_prefix="llm-limiter")


class ModelLimiter:
    """FIFO 信号量：threading.Lock + 计数 + 等待队列（deque[Event] 保证先来先得）"""

    def __init__(self, limit: int):
        self._limit = max(1, int(limit))
        self._inflight = 0
        self._lock = threading.Lock()
        self._waiters: deque = deque()  # threading.Event
        self._pending_limit: Optional[int] = None  # 配置调小时的惰性目标值

    @property
    def limit(self) -> int:
        with self._lock:
            return self._pending_limit if self._pending_limit is not None else self._limit

    def update_limit(self, new_limit: int) -> None:
        """调整限额：调大立即生效（唤醒等待者），调小等自然排空后生效（惰性）"""
        new_limit = max(1, int(new_limit))
        with self._lock:
            if new_limit >= self._limit and self._pending_limit is None:
                self._limit = new_limit
                self._wake_waiters_locked()
            elif new_limit < self._limit:
                self._pending_limit = new_limit

    def _wake_waiters_locked(self) -> int:
        """持锁调用：按可用额度尽量唤醒队首等待者，返回唤醒数"""
        woken = 0
        while self._waiters and self._inflight < self._limit:
            ev = self._waiters.popleft()
            self._inflight += 1
            ev.set()
            woken += 1
        # 排空后应用惰性调小
        if self._pending_limit is not None and not self._waiters and self._inflight <= self._pending_limit:
            self._limit = self._pending_limit
            self._pending_limit = None
        return woken

    def acquire_sync(self, timeout: Optional[float] = None) -> bool:
        """获取槽位（阻塞，FIFO）；超时返回 False（调用方自行决定放行或失败）"""
        with self._lock:
            if self._inflight < self._limit and not self._waiters:
                self._inflight += 1
                return True
            ev = threading.Event()
            self._waiters.append(ev)
        acquired = ev.wait(timeout)
        if acquired:
            return True
        # 超时：若已被唤醒（race：wait 返回 False 但 set 恰在之后发生）则视为成功
        if ev.is_set():
            return True
        with self._lock:
            try:
                self._waiters.remove(ev)
            except ValueError:
                pass  # 已被唤醒但 set 在 wait 超时之后：槽位已记账，直接成功
            else:
                return False
        return True

    def release(self) -> None:
        """释放槽位并唤醒队首等待者"""
        with self._lock:
            if self._waiters:
                ev = self._waiters.popleft()
                ev.set()  # 槽位直接移交给等待者，inflight 不减不减（转移）
                return
            self._inflight = max(0, self._inflight - 1)
            self._wake_waiters_locked()  # 处理惰性调小的落地


_LIMITERS: Dict[str, ModelLimiter] = {}
_GUARD = threading.Lock()


def get_limiter(key: str, limit: int) -> ModelLimiter:
    """进程级单例 registry；limit 变化经 update_limit 生效"""
    lim = max(1, int(limit))
    with _GUARD:
        m = _LIMITERS.get(key)
        if m is None:
            m = ModelLimiter(lim)
            _LIMITERS[key] = m
        elif lim != m.limit:
            m.update_limit(lim)
        return m


def get_inflight(key: str) -> Optional[int]:
    """观测用：该 key 当前在途数（不存在返回 None）"""
    with _GUARD:
        m = _LIMITERS.get(key)
    return None if m is None else m._inflight  # noqa: SLF001 - 观测接口


@asynccontextmanager
async def alimit(key: Optional[str], limit: Optional[int]):
    """async 包装：key/limit 无效时直通零开销；acquire 超时（默认 10 分钟）兜底放行并告警"""
    if not key or not limit or int(limit) <= 0:
        yield
        return
    limiter = get_limiter(key, int(limit))
    acquired_slot = False
    try:
        if limiter.acquire_sync(timeout=0):
            acquired_slot = True  # 快路径：有空槽，无需线程桥接
        else:
            loop = asyncio.get_running_loop()
            acquired_slot = await loop.run_in_executor(_WAIT_POOL, limiter.acquire_sync, 600.0)
            if not acquired_slot:
                logger.warning(
                    f"⚠️ [limiter] key={key} acquire 超时（10min），兜底放行；"
                    f"疑似槽位泄漏，请检查 max_concurrency 配置"
                )
        yield
    finally:
        if acquired_slot:
            limiter.release()
