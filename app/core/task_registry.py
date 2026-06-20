"""全局异步任务跟踪器（TaskRegistry）。

解决 fire-and-forget 协程（`asyncio.create_task` 后无人 await）导致的任务泄漏：

- OperationLogMiddleware 写日志：必须完成，shutdown 时等待 flush
- mcp_health_check_loop 心跳循环：shutdown 时直接 cancel
- _startup_sync 启动同步任务：shutdown 时 cancel

设计要点：

- 单例 + 进程内共享，通过 `task_registry` 直接访问
- 使用 `set[asyncio.Task]` + `task.add_done_callback(_discard)` 自动清理引用，避免内存增长
- 区分 critical（shutdown 等待完成）与非 critical（shutdown 立即 cancel）
- shutdown 顺序：先 cancel 所有非 critical → asyncio.wait(critical, timeout)
- 仅可在事件循环中调用（register/shutdown 都是 async-safe 方法）

线程安全说明：
    ``_discard`` 由事件循环在主线程同步调用（``loop.call_soon`` 调度），
    ``register`` / ``shutdown`` 也在主线程。为避免 ``_discard`` 与
    ``register`` / ``shutdown`` 在事件循环切换点交错修改 ``_tasks`` /
    ``_critical`` / ``_names`` / 计数器，使用 ``threading.Lock`` 保护所有
    读写操作。``threading.Lock`` 是同步原语，``_discard`` 同步函数可以
    直接 ``with`` 进入；``shutdown`` 在持锁快照集合后**先释放锁**再执行
    ``await asyncio.gather / asyncio.wait``，避免在 await 期间长时间持锁。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Awaitable, Dict, Set

logger = logging.getLogger(__name__)


class TaskRegistry:
    """全局后台任务注册表（单例）。"""

    def __init__(self) -> None:
        self._tasks: Set[asyncio.Task] = set()
        self._critical: Set[asyncio.Task] = set()
        # threading.Lock：兼容 _discard 同步回调；CPython asyncio 主线程模型下
        # 也能保证 register / shutdown / _discard 三方对集合的修改串行化
        self._lock = threading.Lock()
        self._names: Dict[int, str] = {}
        self._stats_created = 0
        self._stats_completed = 0
        self._stats_failed = 0

    def register(
        self,
        coro: Awaitable,
        *,
        name: str = "",
        critical: bool = False,
    ) -> asyncio.Task:
        """提交后台任务并加入跟踪集合。

        Args:
            coro: 待执行的协程
            name: 任务名称（仅用于日志/统计）
            critical: True 表示 shutdown 时等待完成；False 表示 shutdown 时立即 cancel

        Returns:
            已注册的 asyncio.Task 对象
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError as exc:
            raise RuntimeError(
                "TaskRegistry.register 必须在事件循环中调用；"
                "worker thread 请通过 run_async / run_coroutine_threadsafe 桥接。"
            ) from exc

        task = loop.create_task(coro, name=name or None)
        task_id = id(task)
        with self._lock:
            self._tasks.add(task)
            self._names[task_id] = name or task.get_name()
            if critical:
                self._critical.add(task)
            self._stats_created += 1
            pending_count = len(self._tasks)

        # 任务完成后自动清理引用，避免内存增长
        def _discard(t: asyncio.Task) -> None:
            display: str
            with self._lock:
                self._tasks.discard(t)
                self._critical.discard(t)
                display = self._names.pop(id(t), t.get_name())
                self._stats_completed += 1
            if t.cancelled():
                logger.debug("TaskRegistry: 任务已取消 name=%s", display)
                return
            exc = t.exception()
            if exc is not None:
                with self._lock:
                    self._stats_failed += 1
                logger.warning(
                    "TaskRegistry: 任务异常 name=%s exc=%r", display, exc
                )

        task.add_done_callback(_discard)
        logger.debug(
            "TaskRegistry: 注册任务 name=%s critical=%s pending=%d",
            name or task.get_name(),
            critical,
            pending_count,
        )
        return task

    async def shutdown(self, timeout: float = 10.0) -> None:
        """shutdown：先 cancel 非 critical → asyncio.wait(critical, timeout)。

        Args:
            timeout: critical 任务等待超时（秒）

        实现要点：
            持锁阶段**仅做集合快照**（拷贝出 pending/non_critical/critical
            三个列表 + names 字典快照），随后立即释放锁；锁外执行 cancel /
            gather / wait，避免在 await 期间长期持锁阻塞 register / _discard。
        """
        # 持锁快照阶段（同步、短暂）
        with self._lock:
            pending = [t for t in self._tasks if not t.done()]
            if not pending:
                logger.info("TaskRegistry.shutdown: 无待处理任务")
                return

            non_critical = [t for t in pending if t not in self._critical]
            critical = [t for t in pending if t in self._critical]
            # 名称映射快照（critical 超时日志需要）
            names_snapshot: Dict[int, str] = dict(self._names)

        # 锁外执行 cancel / await（不阻塞 register / _discard）

        # 1) 先 cancel 非 critical
        for t in non_critical:
            t.cancel()
        if non_critical:
            logger.info(
                "TaskRegistry.shutdown: 已取消 %d 个非 critical 任务",
                len(non_critical),
            )
            # 等待 cancel 完成，忽略 CancelledError
            await asyncio.gather(*non_critical, return_exceptions=True)

        # 2) 再等待 critical 完成（带超时）
        if critical:
            logger.info(
                "TaskRegistry.shutdown: 等待 %d 个 critical 任务完成（timeout=%.1fs）",
                len(critical),
                timeout,
            )
            done, still_pending = await asyncio.wait(
                critical, timeout=timeout
            )
            if still_pending:
                names = [
                    names_snapshot.get(id(t), t.get_name()) for t in still_pending
                ]
                logger.warning(
                    "TaskRegistry.shutdown: %d 个 critical 任务超时被强制取消: %s",
                    len(still_pending),
                    names,
                )
                for t in still_pending:
                    t.cancel()
                await asyncio.gather(*still_pending, return_exceptions=True)

        logger.info("TaskRegistry.shutdown: 完成")

    def pending_count(self) -> int:
        """当前未完成的任务数"""
        with self._lock:
            return sum(1 for t in self._tasks if not t.done())

    def get_stats(self) -> Dict[str, int]:
        """返回注册表统计信息"""
        with self._lock:
            return {
                "pending": sum(1 for t in self._tasks if not t.done()),
                "critical_pending": sum(1 for t in self._critical if not t.done()),
                "total_created": self._stats_created,
                "total_completed": self._stats_completed,
                "total_failed": self._stats_failed,
            }


# 全局单例
task_registry = TaskRegistry()
