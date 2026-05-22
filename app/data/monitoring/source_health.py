"""数据源健康度监控 — 记录调用结果、统计成功率、定期刷入 MongoDB。"""

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.data.storage.mongo.repositories.metadata_repo import MetadataRepo

logger = logging.getLogger(__name__)


class SourceHealthMonitor:
    """数据源健康度统计。"""

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
        self._stats: Dict[str, Dict] = {}
        # (market, source, domain) -> {success, failure, last_success, last_failure, avg_latency_ms}
        self._repo = MetadataRepo()
        self._flush_interval = 30
        self._flush_thread: Optional[threading.Thread] = None
        self._running = False

    def start(self):
        """启动定期刷入线程。"""
        self._running = True
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._flush_thread.start()
        logger.info("健康监控已启动")

    def stop(self):
        self._running = False
        self._flush_to_mongo()

    def record_call(
        self, market: str, source: str, domain: str,
        success: bool, latency_ms: int = 0, error: Optional[str] = None
    ):
        """记录一次数据源调用。"""
        key = f"{market}:{source}:{domain}"
        if key not in self._stats:
            self._stats[key] = {
                "market": market, "source": source, "domain": domain,
                "success_count": 0, "failure_count": 0,
                "total_latency_ms": 0, "call_count": 0,
                "last_success_at": None, "last_failure_at": None,
                "last_error": None,
            }

        s = self._stats[key]
        s["call_count"] += 1
        s["total_latency_ms"] += latency_ms

        if success:
            s["success_count"] += 1
            s["last_success_at"] = datetime.now(timezone.utc).isoformat()
        else:
            s["failure_count"] += 1
            s["last_failure_at"] = datetime.now(timezone.utc).isoformat()
            if error:
                s["last_error"] = error

    def get_health(self, market: str, source: str, domain: str) -> Optional[Dict]:
        """获取健康度数据。"""
        key = f"{market}:{source}:{domain}"
        stats = self._stats.get(key)
        if not stats:
            return None
        return self._compute_health(stats)

    def get_all_health(self, market: Optional[str] = None) -> List[Dict]:
        """获取所有健康度数据。"""
        results = []
        for stats in self._stats.values():
            if market and stats["market"] != market:
                continue
            results.append(self._compute_health(stats))
        return results

    def _compute_health(self, stats: Dict) -> Dict:
        total = stats["success_count"] + stats["failure_count"]
        success_rate = stats["success_count"] / total if total > 0 else 0.0
        avg_latency = stats["total_latency_ms"] / stats["call_count"] if stats["call_count"] > 0 else 0

        return {
            "market": stats["market"],
            "source": stats["source"],
            "domain": stats["domain"],
            "success_rate": round(success_rate, 4),
            "success_count": stats["success_count"],
            "failure_count": stats["failure_count"],
            "avg_latency_ms": round(avg_latency, 1),
            "last_success_at": stats["last_success_at"],
            "last_failure_at": stats["last_failure_at"],
            "last_error": stats["last_error"],
        }

    def _flush_loop(self):
        while self._running:
            time.sleep(self._flush_interval)
            try:
                self._flush_to_mongo()
            except Exception as e:
                logger.error(f"健康度刷入失败: {e}")

    def _flush_to_mongo(self):
        """将内存统计刷入 MongoDB。"""
        import asyncio

        async def _do_flush():
            for stats in list(self._stats.values()):
                health = self._compute_health(stats)
                try:
                    await self._repo.upsert_health(
                        stats["market"], stats["source"], stats["domain"], health
                    )
                except Exception as e:
                    logger.debug(f"刷入健康度失败: {e}")

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # 已有运行中的事件循环（如 uvicorn），提交为任务
            asyncio.ensure_future(_do_flush(), loop=loop)
        else:
            # 无运行中的事件循环（如后台线程），直接运行
            try:
                asyncio.run(_do_flush())
            except Exception as e:
                logger.debug(f"健康度刷入失败: {e}")
