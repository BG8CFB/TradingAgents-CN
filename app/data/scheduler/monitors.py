"""调度任务执行监控 — 超时检测、卡住任务恢复、执行统计。"""

import asyncio
import logging
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)


class SchedulerMonitor:
    """调度任务执行监控器。

    职责：
    1. 检测超时任务（执行时间超过阈值）
    2. 检测卡住的任务（长时间未更新检查点）
    3. 统计任务执行情况（成功率、平均耗时）
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._running_tasks: Dict[str, Dict] = {}
        # 任务超时告警节流表：task_id -> 上次告警时间戳
        self._timeout_warned_at: Dict[str, float] = {}
        self._task_stats: Dict[str, Dict] = defaultdict(
            lambda: {
                "total_runs": 0,
                "success_count": 0,
                "failure_count": 0,
                "total_latency_ms": 0,
                "last_run_at": None,
                "last_status": None,
            }
        )
        self._dict_lock = threading.Lock()
        self._timeout_threshold_seconds = 3600  # 默认超时阈值 1 小时
        self._staleness_threshold_seconds = 86400 * 3  # 默认卡住阈值 3 天
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._running = False
        self._monitor_interval = 60  # 检查间隔 60 秒
        # S3 修复：check_stale_tasks 调用频率控制（每 60 次迭代约 1 小时）。
        self._stale_check_interval = 60
        self._loop_count = 0
        # 主事件循环引用：start() 时从 scheduler 所在 loop 获取，
        # 供监控线程通过 run_coroutine_threadsafe 安全调度协程到主 loop
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None

    def start(self, scheduler: AsyncIOScheduler) -> None:
        """启动监控线程。"""
        self._scheduler = scheduler
        # 获取 scheduler 所在的事件循环，避免监控线程用 asyncio.run 创建新循环
        # 与 Motor 主循环冲突
        try:
            self._main_loop = asyncio.get_running_loop()
        except RuntimeError:
            # start() 可能在非异步上下文调用；退而尝试获取已有 loop
            try:
                self._main_loop = asyncio.get_event_loop()
            except RuntimeError:
                self._main_loop = None
        self._running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        logger.info("调度监控已启动")

    def stop(self) -> None:
        """停止监控。"""
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)

    def on_task_start(self, market: str, domain: str) -> None:
        """记录任务开始。"""
        task_id = f"{market}:{domain}"
        with self._dict_lock:
            self._running_tasks[task_id] = {
                "market": market,
                "domain": domain,
                "started_at": time.time(),
                "started_at_iso": datetime.now(timezone.utc).isoformat(),
            }

    def on_task_complete(
        self, market: str, domain: str, success: bool, latency_ms: int = 0
    ) -> None:
        """记录任务完成。"""
        task_id = f"{market}:{domain}"
        with self._dict_lock:
            self._running_tasks.pop(task_id, None)
            self._timeout_warned_at.pop(task_id, None)

            stats = self._task_stats[task_id]
            stats["total_runs"] += 1
            stats["total_latency_ms"] += latency_ms
            stats["last_run_at"] = datetime.now(timezone.utc).isoformat()
            stats["last_status"] = "success" if success else "failure"

            if success:
                stats["success_count"] += 1
            else:
                stats["failure_count"] += 1

    def get_task_stats(self, market: Optional[str] = None) -> List[Dict]:
        """获取任务执行统计。"""
        results = []
        with self._dict_lock:
            snapshot = list(self._task_stats.items())
        for task_id, stats in snapshot:
            if market and not task_id.startswith(f"{market}:"):
                continue
            total = stats["total_runs"]
            avg_latency = stats["total_latency_ms"] / total if total > 0 else 0
            results.append(
                {
                    "task_id": task_id,
                    "total_runs": total,
                    "success_count": stats["success_count"],
                    "failure_count": stats["failure_count"],
                    "success_rate": round(stats["success_count"] / total, 4)
                    if total > 0
                    else 0,
                    "avg_latency_ms": round(avg_latency, 1),
                    "last_run_at": stats["last_run_at"],
                    "last_status": stats["last_status"],
                }
            )
        return results

    def get_running_tasks(self) -> List[Dict]:
        """获取当前运行中的任务。"""
        now = time.time()
        results = []
        with self._dict_lock:
            snapshot = list(self._running_tasks.items())
        for task_id, info in snapshot:
            elapsed = int((now - info["started_at"]) * 1000)
            results.append(
                {
                    "task_id": task_id,
                    "market": info["market"],
                    "domain": info["domain"],
                    "started_at": info["started_at_iso"],
                    "elapsed_ms": elapsed,
                    "is_timeout": elapsed > self._timeout_threshold_seconds * 1000,
                }
            )
        return results

    def check_stale_tasks(self) -> None:
        """检测卡住的任务（检查点长时间未更新）。

        fire-and-forget：提交到主事件循环后立即返回，不阻塞监控线程。
        检测结果在协程内部直接 log warning。
        """
        from app.data.scheduler.checkpoint import CheckpointManager

        async def _check():
            try:
                results = []
                checkpoint = CheckpointManager()
                with self._dict_lock:
                    task_snapshot = list(self._task_stats.items())
                for task_id, stats in task_snapshot:
                    parts = task_id.split(":")
                    if len(parts) != 2:
                        continue
                    market, domain = parts
                    cp = await checkpoint.get_checkpoint_doc(market, domain, "scheduled")
                    if cp:
                        from datetime import datetime as _dt

                        try:
                            last_sync = _dt.fromisoformat(cp.get("last_sync_time", ""))
                            if last_sync.tzinfo is None:
                                last_sync = last_sync.replace(tzinfo=timezone.utc)
                            age = (_dt.now(timezone.utc) - last_sync).total_seconds()
                            if age > self._staleness_threshold_seconds:
                                results.append(
                                    {
                                        "task_id": task_id,
                                        "market": market,
                                        "domain": domain,
                                        "last_sync_time": str(last_sync),
                                        "staleness_hours": round(age / 3600, 1),
                                    }
                                )
                        except (ValueError, TypeError) as parse_err:
                            logger.debug(
                                "跳过检查点 %s:%s 的时间解析: %s",
                                market, domain, parse_err,
                            )
                # 在协程内部直接输出检测结果
                for t in results:
                    logger.warning(
                        "检测到卡住的任务: %s, 已停滞 %s 小时",
                        t["task_id"], t["staleness_hours"],
                    )
            except Exception as e:
                logger.debug(f"卡住任务检测失败: {e}")

        # fire-and-forget：提交到主循环后立即返回，不调 future.result()，
        # 避免主循环繁忙时阻塞后台监控线程导致后续检测延迟。
        from app.core.async_utils import run_async_fire_and_forget

        run_async_fire_and_forget(_check())

    def _monitor_loop(self) -> None:
        """定期监控循环。"""
        while self._running:
            time.sleep(self._monitor_interval)
            self._loop_count += 1
            try:
                self._check_timeouts()
                # S3 修复：定期检查卡住的任务（checkpoint 长时间未更新）。
                if self._loop_count % self._stale_check_interval == 0:
                    self.check_stale_tasks()
            except Exception as e:
                logger.error(f"监控循环异常: {e}")

    def _check_timeouts(self) -> None:
        """检查超时任务。"""
        now = time.time()
        with self._dict_lock:
            snapshot = list(self._running_tasks.items())
        for task_id, info in snapshot:
            elapsed = now - info["started_at"]
            if elapsed > self._timeout_threshold_seconds:
                # 节流：同一任务 10 分钟内只告警一次，避免监控循环刷屏
                last_warn = self._timeout_warned_at.get(task_id, 0.0)
                if now - last_warn >= 600:
                    self._timeout_warned_at[task_id] = now
                    logger.warning(f"任务超时: {task_id}, 已运行 {int(elapsed / 60)} 分钟")
                # 记录到 sync_events
                self._record_timeout_event(info, elapsed)

    def _record_timeout_event(self, info: Dict, elapsed: float) -> None:
        """记录超时事件到 sync_events。

        监控线程中调用：fire-and-forget 提交到主事件循环，不阻塞监控线程。
        """
        from app.data.storage.mongo.repositories.metadata_repo import MetadataRepo

        async def _record():
            try:
                repo = MetadataRepo()
                await repo.insert_event(
                    {
                        "event_type": "TASK_TIMEOUT",
                        "market": info["market"],
                        "domain": info["domain"],
                        "elapsed_seconds": int(elapsed),
                        "started_at": info["started_at_iso"],
                    }
                )
            except Exception as e:
                logger.debug(f"超时事件记录失败: {e}")

        # fire-and-forget：提交到主循环后立即返回，不调 future.result()，
        # 避免多任务超时或主循环繁忙时阻塞后台监控线程。
        from app.core.async_utils import run_async_fire_and_forget

        run_async_fire_and_forget(_record())
