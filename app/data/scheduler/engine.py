"""调度引擎 — 基于 APScheduler。"""

import asyncio
import logging
import os
import threading
import time
from typing import Dict, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.data.scheduler.job_registry import JobRegistry
from app.data.scheduler.checkpoint import CheckpointManager
from app.data.scheduler.dependencies import DependencyGraph

logger = logging.getLogger(__name__)


class SchedulerEngine:
    """调度引擎，管理三市场的定时同步任务。"""

    _instance: Optional["SchedulerEngine"] = None
    _instance_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._instance_lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                cls._instance = instance
            return cls._instance

    def __init__(self, scheduler: Optional[AsyncIOScheduler] = None):
        with self._instance_lock:
            if getattr(self, "_initialized", False):
                return
            self._initialized = True
        self._scheduler = scheduler or AsyncIOScheduler(timezone="UTC")
        self._registry = JobRegistry()
        self._checkpoint = CheckpointManager()
        self._dependency_graph = DependencyGraph()
        self._job_configs: Dict[tuple[str, str], Dict] = {}
        self._jobs_registered = False

    @classmethod
    def get_instance(cls) -> Optional["SchedulerEngine"]:
        return cls._instance

    def get_scheduler(self) -> AsyncIOScheduler:
        return self._scheduler

    def start(self) -> None:
        if not self._scheduler.running:
            self._register_all_jobs()
            self._load_all_schedules()
            self._scheduler.start()
            logger.info(
                "调度引擎已启动，共注册 %d 个任务", len(self._registry.list_jobs())
            )

    def shutdown(self, wait: bool = True) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=wait)
            logger.info("调度引擎已停止")

    def _register_all_jobs(self) -> None:
        if self._jobs_registered:
            return
        from app.data.scheduler.jobs.cn import register_cn_jobs
        from app.data.scheduler.jobs.hk import register_hk_jobs
        from app.data.scheduler.jobs.us import register_us_jobs

        register_cn_jobs(self._registry)
        register_hk_jobs(self._registry)
        register_us_jobs(self._registry)
        self._jobs_registered = True

    def _load_all_schedules(self) -> None:
        base = os.path.dirname(__file__)
        for market_code, folder in [("CN", "cn"), ("HK", "hk"), ("US", "us")]:
            yaml_path = os.path.join(base, "jobs", folder, "schedule.yaml")
            self.load_schedule(market_code, yaml_path)

    def load_schedule(self, market: str, yaml_path: str) -> None:
        """加载市场调度配置并注册任务。"""
        import yaml

        if not os.path.exists(yaml_path):
            logger.warning("调度配置不存在: %s", yaml_path)
            return

        with open(yaml_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

        for domain, job_conf in config.items():
            if not isinstance(job_conf, dict):
                continue

            cron_expr = job_conf.get("cron")
            if not cron_expr:
                continue

            self._job_configs[(market, domain)] = job_conf
            for dep in job_conf.get("depends_on", []) or []:
                self._dependency_graph.add_dependency(
                    f"{market}:{domain}", f"{market}:{dep}"
                )

            timezone = job_conf.get("timezone", "UTC")
            job_id = f"{market.lower()}_{domain}"

            try:
                parts = cron_expr.split()
                trigger = CronTrigger(
                    minute=parts[0] if len(parts) > 0 else "*",
                    hour=parts[1] if len(parts) > 1 else "*",
                    day=parts[2] if len(parts) > 2 else "*",
                    month=parts[3] if len(parts) > 3 else "*",
                    day_of_week=parts[4] if len(parts) > 4 else "*",
                    timezone=timezone,
                )
                self._scheduler.add_job(
                    self._make_job_func(market, domain),
                    trigger=trigger,
                    id=job_id,
                    replace_existing=True,
                    max_instances=1,
                    # 错过触发窗口的处理策略：
                    # - misfire_grace_time=300：超过 5 分钟的堆积任务丢弃，避免重启后
                    #   把长时间累积的 misfire 一次性补跑导致数据库被打挂
                    # - coalesce=True：多个错过的实例合并为 1 次，避免重复执行
                    misfire_grace_time=300,
                    coalesce=True,
                )
                logger.info("注册调度: %s (%s %s)", job_id, cron_expr, timezone)
            except Exception as e:
                logger.error("注册调度失败 %s: %s", job_id, e)

    def _make_job_func(self, market: str, domain: str):
        """创建任务函数 — 从 JobRegistry 查找并执行对应 Job。"""

        async def job():
            await self._run_job_with_dependencies(market, domain, set(), force=False)

        return job

    async def _run_job_with_dependencies(
        self,
        market: str,
        domain: str,
        visited: set[str],
        force: bool = False,
        mode: Optional[str] = None,
        source: Optional[str] = None,
    ) -> None:
        node_key = f"{market}:{domain}"
        if node_key in visited:
            return
        visited.add(node_key)

        job_conf = self._job_configs.get((market, domain), {})
        for dep in job_conf.get("depends_on", []) or []:
            # H4 修复：依赖递归执行会绕过 APScheduler max_instances=1 保护。
            # 如果依赖域已在运行中（定时触发或手动触发），跳过递归执行，
            # 避免同一域并发同步导致限流配额双倍消耗。
            monitor = self._get_monitor()
            if monitor:
                dep_task_id = f"{market}:{dep}"
                running = monitor.get_running_tasks()
                if any(r["task_id"] == dep_task_id for r in running):
                    logger.info("依赖域 %s 已在执行中，跳过递归执行", dep_task_id)
                    continue
            # M13 修复：force 只应用于目标域，递归依赖用 force=False，
            # 避免手动触发时依赖域跳过非交易日检查。
            # mode/source 同理：依赖域回落 schedule.yaml 默认，不被手动触发覆盖。
            await self._run_job_with_dependencies(market, dep, visited, force=False)

        logger.debug("执行调度: %s/%s", market, domain)
        job_entry = self._registry.get_job(domain, market)
        if not job_entry or not job_entry.get("class"):
            logger.warning("未注册任务: %s/%s", market, domain)
            return

        # 调用监控钩子（若已启动）记录任务开始
        monitor = self._get_monitor()
        if monitor:
            monitor.on_task_start(market, domain)
        start_ts = time.time()

        try:
            job_instance = job_entry["class"]()
            # mode/source 为手动触发时调用方传入的覆盖值（None=用 schedule.yaml 默认），
            # 仅作用于目标域（依赖递归不传，见上方 M13 注释）
            job_instance.sync_mode = mode or job_conf.get("mode", "incremental")
            job_instance.preferred_source = (
                source if source is not None else job_conf.get("source")
            )
            job_instance.dependencies = list(job_conf.get("depends_on", []) or [])
            job_instance.force_sync = force
            result = await job_instance.execute()
            logger.debug("调度完成 %s/%s: %s", market, domain, result)
        except Exception as e:
            logger.error("调度执行失败 %s/%s: %s", market, domain, e)
            # M14 修复：监控回调用独立 try-except 包裹，避免回调异常
            # 掩盖任务的真实执行结果或导致成功任务被误标为失败。
            if monitor:
                try:
                    monitor.on_task_complete(
                        market,
                        domain,
                        success=False,
                        latency_ms=int((time.time() - start_ts) * 1000),
                    )
                except Exception as monitor_err:
                    logger.warning("监控回调 on_task_complete(False) 异常: %s", monitor_err)
            return

        # 任务成功：在 try/except 外部调用监控回调
        # M14 修复：此前回调在 try 块内调用，回调异常会跳到 except 块再次
        # 以 success=False 调用，导致成功任务被误标为失败。
        if monitor:
            try:
                monitor.on_task_complete(
                    market,
                    domain,
                    success=True,
                    latency_ms=int((time.time() - start_ts) * 1000),
                )
            except Exception as monitor_err:
                logger.warning("监控回调 on_task_complete(True) 异常: %s", monitor_err)

    @staticmethod
    def _get_monitor():
        """获取已启动的 SchedulerMonitor 单例（未启动则返回 None）。"""
        try:
            from app.data.scheduler.monitors import SchedulerMonitor

            monitor = SchedulerMonitor()
            if getattr(monitor, "_running", False):
                return monitor
        except Exception as e:
            # L5 修复：记录异常线索，避免 import 错误或初始化异常被完全吞没。
            logger.debug(f"获取 SchedulerMonitor 失败: {e}")
        return None

    async def trigger_job(
        self,
        market: str,
        domain: str,
        mode: Optional[str] = None,
        source: Optional[str] = None,
    ) -> str:
        """手动触发任务（阻塞等待执行完成；HTTP 端点请用 run_job_now）。"""
        market = market.upper()
        job_id = f"{market.lower()}_{domain}"
        if self._registry.get_job(domain, market):
            try:
                await self._run_job_with_dependencies(
                    market, domain, set(), force=True, mode=mode, source=source
                )
                return job_id
            except Exception as e:
                logger.error("手动触发失败 %s: %s", job_id, e)
        return ""

    def run_job_now(
        self,
        market: str,
        domain: str,
        mode: Optional[str] = None,
        source: Optional[str] = None,
    ) -> Dict:
        """手动触发任务并立即返回（同步方法），同步在后台执行。

        与 trigger_job（阻塞跑完）不同：分钟~小时级的同步不能占用
        HTTP 请求生命周期，执行交给 TaskRegistry 后台任务
        （critical=False，进程 shutdown 时 cancel）。

        目标域已在运行时返回 already_running（幂等，不重复执行），
        避免异步化后重复触发导致同域并发同步。检查与注册之间存在
        非原子窗口，手动触发场景可接受，不引入分布式锁。
        """
        from app.core.task_registry import task_registry

        market = market.upper()
        task_id = f"{market}:{domain}"
        job_id = f"{market.lower()}_{domain}"
        if not self._registry.get_job(domain, market):
            logger.warning("手动触发未注册任务: %s", task_id)
            return {"task_id": task_id, "job_id": job_id, "status": "failed"}

        monitor = self._get_monitor()
        if monitor and any(
            r["task_id"] == task_id for r in monitor.get_running_tasks()
        ):
            logger.info("手动触发跳过（已在执行中）: %s", task_id)
            return {"task_id": task_id, "job_id": job_id, "status": "already_running"}

        task_registry.register(
            self._run_job_with_shutdown_compensation(market, domain, mode, source),
            name=f"manual_sync_{job_id}",
            critical=False,
        )
        return {"task_id": task_id, "job_id": job_id, "status": "triggered"}

    async def _run_job_with_shutdown_compensation(
        self, market: str, domain: str, mode: Optional[str], source: Optional[str]
    ) -> None:
        """执行同步；被 cancel 时补写 SYNC_FAILED 终态事件后重新抛出。

        TaskRegistry 非 critical 任务在 shutdown 时被直接 cancel，而
        BaseSyncJob.execute 与 _run_job_with_dependencies 的 except Exception
        均捕不到 CancelledError（BaseException），否则会留下无终态的
        SYNC_START 事件。
        """
        try:
            await self._run_job_with_dependencies(
                market, domain, set(), force=True, mode=mode, source=source
            )
        except asyncio.CancelledError:
            logger.warning("手动同步被取消（进程 shutdown）: %s/%s", market, domain)
            try:
                from app.data.storage.mongo.repositories.metadata_repo import (
                    MetadataRepo,
                )

                await MetadataRepo().insert_event(
                    {
                        "event_type": "SYNC_FAILED",
                        "market": market,
                        "domain": domain,
                        "error": "cancelled: process shutdown",
                    }
                )
            except Exception as e:
                logger.warning("写入取消补偿事件失败 %s/%s: %s", market, domain, e)
            raise

    def get_job_status(self, job_id: str) -> Optional[Dict]:
        job = self._scheduler.get_job(job_id)
        if job:
            return {
                "id": job.id,
                "next_run_time": str(job.next_run_time) if job.next_run_time else None,
                "status": "running" if job.next_run_time else "paused",
            }
        return None
