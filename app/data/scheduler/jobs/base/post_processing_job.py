"""后处理任务基类 — 触发 PeriodAggregator / AdjFactorCalculator。"""

import logging
import time
from abc import ABC, abstractmethod

from app.data.storage.mongo.repositories.metadata_repo import MetadataRepo

logger = logging.getLogger(__name__)


class PostProcessingJob(ABC):
    """后处理任务基类。"""

    def __init__(self, market: str, job_type: str):
        self.market = market
        self.job_type = job_type
        self._metadata = MetadataRepo()

    async def execute(self) -> dict:
        """执行后处理任务。"""
        start = time.time()
        try:
            count = await self._run()
            elapsed = int((time.time() - start) * 1000)
            await self._metadata.insert_event({
                "event_type": "POST_PROCESS_SUCCESS",
                "market": self.market,
                "domain": self.job_type,
                "record_count": count,
                "latency_ms": elapsed,
            })
            return {"status": "success", "count": count, "latency_ms": elapsed}
        except Exception as e:
            elapsed = int((time.time() - start) * 1000)
            logger.error(f"后处理失败 {self.market}/{self.job_type}: {e}")
            await self._metadata.insert_event({
                "event_type": "POST_PROCESS_FAILED",
                "market": self.market,
                "domain": self.job_type,
                "error": str(e),
                "latency_ms": elapsed,
            })
            return {"status": "failed", "error": str(e)}

    @abstractmethod
    async def _run(self) -> int:
        """执行后处理逻辑，返回处理记录数。"""
        ...


class PeriodAggregationJob(PostProcessingJob):
    """周期聚合任务 — 日线 → 周线/月线。"""

    def __init__(self, market: str, period: str = "weekly"):
        super().__init__(market, f"period_aggregation_{period}")
        self.period = period

    async def _run(self) -> int:
        from app.data.processor.post_processors.period_aggregator import PeriodAggregator
        aggregator = PeriodAggregator()
        return await aggregator.aggregate(self.market, self.period)


class AdjFactorCalcJob(PostProcessingJob):
    """复权因子推导任务。"""

    def __init__(self, market: str):
        super().__init__(market, "adj_factor_calc")

    async def _run(self) -> int:
        from app.data.processor.post_processors.adj_factor_calculator import AdjFactorCalculator
        calculator = AdjFactorCalculator()
        return await calculator.calculate(self.market)
