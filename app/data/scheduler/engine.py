"""调度引擎 — 基于 APScheduler。"""

import logging
import os
import threading
import time
from datetime import datetime
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
        self._trading_day_cache: Dict[str, bool] = {}

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

            # enabled: false 时跳过该任务（不在调度器中注册），保留 cron 配置以便后续恢复
            if job_conf.get("enabled", True) is False:
                logger.info("调度任务已禁用，跳过注册: %s/%s", market, domain)
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
        self, market: str, domain: str, visited: set[str], force: bool = False
    ) -> None:
        node_key = f"{market}:{domain}"
        if node_key in visited:
            return
        visited.add(node_key)

        job_conf = self._job_configs.get((market, domain), {})

        # 交易日门控：仅对"限定工作日"的定时任务，在非交易日跳过，避免假日空跑/浪费配额。
        # 手动触发(force=True)、每日任务(cron day_of_week='*')、日历不可用时均 fail-open 照常执行。
        if not force and await self._should_skip_non_trading_day(market, job_conf):
            logger.info("跳过非交易日任务 %s/%s", market, domain)
            return
        for dep in job_conf.get("depends_on", []) or []:
            await self._run_job_with_dependencies(market, dep, visited, force=force)

        logger.info("执行调度: %s/%s", market, domain)
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
            job_instance.sync_mode = job_conf.get("mode", "incremental")
            job_instance.preferred_source = job_conf.get("source")
            job_instance.dependencies = list(job_conf.get("depends_on", []) or [])
            job_instance.force_sync = force
            result = await job_instance.execute()
            logger.info("调度完成 %s/%s: %s", market, domain, result)
            if monitor:
                monitor.on_task_complete(
                    market,
                    domain,
                    success=True,
                    latency_ms=int((time.time() - start_ts) * 1000),
                )
        except Exception as e:
            logger.error("调度执行失败 %s/%s: %s", market, domain, e)
            if monitor:
                monitor.on_task_complete(
                    market,
                    domain,
                    success=False,
                    latency_ms=int((time.time() - start_ts) * 1000),
                )

    @staticmethod
    def _get_monitor():
        """获取已启动的 SchedulerMonitor 单例（未启动则返回 None）。"""
        try:
            from app.data.scheduler.monitors import SchedulerMonitor

            monitor = SchedulerMonitor()
            if getattr(monitor, "_running", False):
                return monitor
        except Exception:
            pass
        return None

    async def _should_skip_non_trading_day(self, market: str, job_conf: Dict) -> bool:
        """判断任务是否应因"非交易日"跳过。

        仅当 cron 的 day_of_week 被限定（非 '*'）时才门控；每日任务(* *) 不门控。
        日历不可用时 fail-open（返回 False，不跳过）。
        """
        cron = job_conf.get("cron", "")
        parts = cron.split()
        if len(parts) < 5:
            return False
        dow = parts[4].strip()
        if dow == "*" or dow == "":
            return False
        try:
            import pytz

            tz = pytz.timezone(job_conf.get("timezone", "Asia/Shanghai"))
        except Exception:
            try:
                from zoneinfo import ZoneInfo

                tz = ZoneInfo(job_conf.get("timezone", "Asia/Shanghai"))
            except Exception:
                tz = None
        if tz is None:
            return False
        today = datetime.now(tz).date()
        is_td = await self._is_trading_day(market, today)
        return not is_td

    async def _is_trading_day(self, market: str, check_date) -> bool:
        """查 trade_calendar 判断是否为交易日。

        - 有记录且 is_open 为真 → 交易日
        - 无任何日历记录 → fail-open 返回 True（照常执行，避免日历未就绪导致静默丢失同步）
        - 查询异常 → fail-open 返回 True
        """
        cache_key = f"{market}:{check_date.strftime('%Y%m%d')}"
        if cache_key in self._trading_day_cache:
            return self._trading_day_cache[cache_key]
        result = True
        try:
            from app.data.core.interface import DataInterface

            di = DataInterface.get_instance()
            ds = check_date.strftime("%Y-%m-%d")
            res = await di.read(market, "trade_calendar", start_date=ds, end_date=ds)
            rows = res.get("data") or []
            if not rows:
                result = True
            else:
                result = any(r.get("is_open") in (1, True, "1") for r in rows)
        except Exception as e:
            logger.warning("交易日判断失败，fail-open 照常执行 %s/%s: %s", market, check_date, e)
            result = True
        self._trading_day_cache[cache_key] = result
        return result

    async def trigger_job(self, market: str, domain: str) -> str:
        """手动触发任务。"""
        market = market.upper()
        job_id = f"{market.lower()}_{domain}"
        if self._registry.get_job(domain, market):
            try:
                await self._run_job_with_dependencies(market, domain, set(), force=True)
                return job_id
            except Exception as e:
                logger.error("手动触发失败 %s: %s", job_id, e)
        return ""

    def get_job_status(self, job_id: str) -> Optional[Dict]:
        job = self._scheduler.get_job(job_id)
        if job:
            return {
                "id": job.id,
                "next_run_time": str(job.next_run_time) if job.next_run_time else None,
                "status": "running" if job.next_run_time else "paused",
            }
        return None
