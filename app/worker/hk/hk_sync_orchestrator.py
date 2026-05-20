"""
港股同步编排器

参照 A 股 cn_sync_orchestrator.py 结构。
当前仅实现基础信息和日线行情的按需同步。
"""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.data.processor.fallback_router import FallbackRouter
from app.utils.time_utils import now_utc

logger = logging.getLogger(__name__)


@dataclass
class HKSyncResult:
    success: bool = False
    domains: Dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0


class HKSyncOrchestrator:
    """港股同步编排器"""

    def __init__(self, router: Optional[FallbackRouter] = None):
        self._router = router or FallbackRouter()

    async def sync_basic_info(self) -> HKSyncResult:
        from .domain_sync.basic_info_sync import HKBasicInfoSync
        sync = HKBasicInfoSync(router=self._router)
        result = await sync.sync()
        return HKSyncResult(
            success=result.success,
            domains={"basic_info": result.to_dict()},
            duration_ms=result.duration_ms,
        )

    async def sync_all(self) -> HKSyncResult:
        """同步所有港股数据域"""
        start = now_utc()
        results: Dict[str, Any] = {}
        all_success = True

        tasks = [
            ("basic_info", self.sync_basic_info()),
        ]

        for name, coro in tasks:
            try:
                r = await coro
                results[name] = r.domains.get(name, {})
                if not r.success:
                    all_success = False
            except Exception as e:
                logger.error(f"HK sync {name} 失败: {e}")
                results[name] = {"success": False, "error": str(e)}
                all_success = False

        elapsed = (now_utc() - start).total_seconds() * 1000
        return HKSyncResult(success=all_success, domains=results, duration_ms=int(elapsed))
