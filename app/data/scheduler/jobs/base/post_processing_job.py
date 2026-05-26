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
    """周期聚合任务 — 日线 → 周线/月线。

    流程：从 daily_quotes 读取所有日线数据 → 按 symbol 分组 →
    调用 PeriodAggregator 聚合 → 将结果写回 daily_quotes（period 字段区分）。
    """

    def __init__(self, market: str, period: str = "weekly"):
        super().__init__(market, f"period_aggregation_{period}")
        self.period = period

    async def _run(self) -> int:
        from datetime import datetime, timedelta

        from app.data.processor.post_processors.period_aggregator import PeriodAggregator
        from app.data.storage.mongo.collections import get_collection_name
        from app.data.storage.mongo.client import get_motor_db

        aggregator = PeriodAggregator()
        db = get_motor_db()
        coll_name = get_collection_name("daily_quotes", self.market)
        coll = db[coll_name]

        # 读取近 2 年的日线数据（足够覆盖周线/月线聚合）
        cutoff = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
        cursor = coll.find(
            {"trade_date": {"$gte": cutoff}, "period": {"$in": ["daily", None]}},
            {"_id": 0},
        ).sort("symbol", 1)
        daily_records = await cursor.to_list(length=None)
        if not daily_records:
            return 0

        # 按 symbol 分组
        groups: dict[str, list] = {}
        for rec in daily_records:
            sym = rec.get("symbol", "UNKNOWN")
            groups.setdefault(sym, []).append(rec)

        total = 0
        from pymongo import UpdateOne

        for sym, records in groups.items():
            if self.period == "weekly":
                aggregated = aggregator.aggregate_to_weekly(records)
            else:
                aggregated = aggregator.aggregate_to_monthly(records)

            if not aggregated:
                continue

            ops = []
            for rec in aggregated:
                td = rec.get("trade_date")
                if not td:
                    continue
                ops.append(UpdateOne(
                    {"symbol": sym, "trade_date": td, "period": self.period},
                    {"$set": rec},
                    upsert=True,
                ))
            if ops:
                result = await coll.bulk_write(ops, ordered=False)
                total += result.upserted_count + result.modified_count

        return total


class AdjFactorCalcJob(PostProcessingJob):
    """复权因子推导任务。

    流程：从 corporate_actions 读取公司行为 → 按 symbol 分组 →
    调用 AdjFactorCalculator 推导复权因子 → 写入 adj_factors 集合。
    """

    def __init__(self, market: str):
        super().__init__(market, "adj_factor_calc")

    async def _run(self) -> int:
        from app.data.processor.post_processors.adj_factor_calculator import AdjFactorCalculator
        from app.data.storage.mongo.collections import get_collection_name
        from app.data.storage.mongo.client import get_motor_db
        from pymongo import UpdateOne

        calculator = AdjFactorCalculator()
        db = get_motor_db()

        # 读取所有公司行为
        ca_coll = db[get_collection_name("corporate_actions", self.market)]
        cursor = ca_coll.find({}, {"_id": 0}).sort("ex_date", 1)
        actions = await cursor.to_list(length=None)
        if not actions:
            return 0

        # 按 symbol 分组
        groups: dict[str, list] = {}
        for act in actions:
            sym = act.get("symbol", "UNKNOWN")
            groups.setdefault(sym, []).append(act)

        total = 0
        adj_coll = db[get_collection_name("adj_factors", self.market)]

        for sym, sym_actions in groups.items():
            adj_records = calculator.calculate_from_corporate_actions(sym_actions)
            if not adj_records:
                continue

            ops = []
            for rec in adj_records:
                td = rec.get("trade_date")
                if not td:
                    continue
                ops.append(UpdateOne(
                    {"symbol": sym, "trade_date": td},
                    {"$set": rec},
                    upsert=True,
                ))
            if ops:
                result = await adj_coll.bulk_write(ops, ordered=False)
                total += result.upserted_count + result.modified_count

        return total
