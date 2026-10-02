"""计算型任务基类 — 读库内标准域 → 批量计算 → 写结果域。

与 BaseSyncJob 的区别：不走 FallbackRouter/checkpoint 的外部数据同步流程，
输入全部来自库内标准集合。保留两件事以复用现有调度链路：
1. engine 的属性注入约定（sync_mode/preferred_source/dependencies/force_sync）
2. 非交易日跳过 + sync_events 终态事件（SchedulerMonitor/手动触发依赖）
"""

import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class ComputeJob(ABC):
    market: str = "CN"
    domain: str = ""

    # engine 注入属性（计算任务仅消费 force_sync；其余接收不使用）
    sync_mode: str = "incremental"
    preferred_source: Optional[str] = None
    dependencies: list = []
    force_sync: bool = False

    async def execute(self) -> Dict:
        from app.data.storage.mongo.repositories.metadata_repo import MetadataRepo

        start = time.time()
        await MetadataRepo().insert_event({
            "event_type": "SYNC_START",
            "market": self.market,
            "domain": self.domain,
            "started_at": datetime.now(timezone.utc).isoformat(),
        })
        # 非交易日跳过（手动 force 触发不跳）
        if not self.force_sync and await self._should_skip_non_trading_day():
            await MetadataRepo().insert_event({
                "event_type": "SYNC_SKIPPED",
                "market": self.market,
                "domain": self.domain,
                "reason": "non_trading_day",
            })
            return {"status": "skipped", "reason": "non_trading_day"}

        try:
            result = await self.compute()
            await MetadataRepo().insert_event({
                "event_type": "SYNC_SUCCESS",
                "market": self.market,
                "domain": self.domain,
                "result": result,
                "latency_ms": int((time.time() - start) * 1000),
            })
            return result
        except Exception as e:
            # re-raise：调度引擎的 except 分支据此触发 monitor 失败回调（M14 语义）
            logger.error("计算任务失败 %s/%s: %s", self.market, self.domain, e,
                         exc_info=True)
            await MetadataRepo().insert_event({
                "event_type": "SYNC_FAILED",
                "market": self.market,
                "domain": self.domain,
                "error": str(e),
                "latency_ms": int((time.time() - start) * 1000),
            })
            raise

    async def _should_skip_non_trading_day(self) -> bool:
        from app.data.core.market import is_trading_day

        # is_trading_day(market) 不传日期时默认取当天（对齐 BaseSyncJob._is_trading_day）
        return not await is_trading_day(self.market)

    @abstractmethod
    async def compute(self) -> Dict:
        """执行计算并返回摘要 dict。"""
        ...
