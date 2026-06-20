"""周线/月线聚合同步"""

import logging
import time
from typing import Any, Dict, List, Optional

from .base_domain_sync import BaseDomainSync, DomainSyncResult
from app.data.processor.aggregation import aggregate_period
from app.data.storage.mongo.collections import get_collection_name

logger = logging.getLogger(__name__)


class AggregationSync(BaseDomainSync):
    """周线/月线聚合（依赖日线数据）

    Note:
        ``aggregate_period`` 内部用 ``df.groupby("period_key")`` 整体聚合，
        要求**同一周/月的所有日线在同一个 DataFrame**。若按固定 batch_size
        切分，跨周边界的 batch 会被各自聚合，产生 2 条不同 trade_date 的
        周线记录（upsert filter 也不命中 → 数据膨胀）。

        因此本同步器**一次性读取单 symbol 全部日线**后再整体聚合。
        单 symbol 10 年日线约 2400 条 ≈ 0.5 MB，内存可接受；
        多 symbol 场景由上层 ``AggregationSyncJob`` 逐 symbol 调用本方法。
    """

    domain = "daily_quotes"
    description = "周线/月线聚合（从日线数据计算）"

    async def sync(
        self,
        symbol: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        **kwargs,
    ) -> DomainSyncResult:
        start = time.monotonic()
        period = kwargs.get("period", "weekly")

        if not symbol:
            return DomainSyncResult(
                domain=self.domain, success=False,
                error="必须指定 symbol 参数",
                duration_ms=int((time.monotonic() - start) * 1000),
            )

        try:
            daily_quotes = await self._read_daily_quotes(symbol, start_date, end_date)
            if not daily_quotes:
                duration_ms = int((time.monotonic() - start) * 1000)
                result = DomainSyncResult(
                    domain=self.domain, success=False,
                    error="无日线数据可聚合或聚合结果为空",
                    duration_ms=duration_ms,
                )
            else:
                aggregated = aggregate_period(daily_quotes, period=period)
                if not aggregated:
                    duration_ms = int((time.monotonic() - start) * 1000)
                    result = DomainSyncResult(
                        domain=self.domain, success=False,
                        error="聚合结果为空",
                        duration_ms=duration_ms,
                    )
                else:
                    written = await self._write_to_mongo(
                        aggregated, "aggregation",
                        filter_fields=["symbol", "trade_date", "period"],
                    )
                    duration_ms = int((time.monotonic() - start) * 1000)
                    result = DomainSyncResult(
                        domain=self.domain,
                        success=True,
                        source="aggregation",
                        records_synced=written,
                        duration_ms=duration_ms,
                    )

        except Exception as e:
            duration_ms = int((time.monotonic() - start) * 1000)
            result = DomainSyncResult(
                domain=self.domain, success=False,
                error=str(e), duration_ms=duration_ms,
            )

        await self._write_sync_event(result, "SYNC_SUCCESS" if result.success else "SYNC_FAILED")
        return result

    async def _read_daily_quotes(
        self, symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """一次性读取单 symbol 的全部日线数据。

        单 symbol 10 年日线约 2400 条，内存占用约 0.5 MB，可安全全量载入。
        一次性读取是 ``aggregate_period`` 整体 groupby 的前提 — 分批会
        破坏周/月聚合语义（见类 docstring）。
        """
        try:
            from app.core.database import get_mongo_db
            db = get_mongo_db()
        except Exception as e:
            logger.debug(f"获取数据库连接失败: {e}")
            return []

        # 修复参数顺序：get_collection_name(domain, market)
        collection_name = get_collection_name("daily_quotes", "CN")
        collection = db[collection_name]

        query: Dict[str, Any] = {"symbol": symbol, "period": {"$in": ["daily", None]}}
        if start_date:
            query["trade_date"] = {"$gte": start_date}
        if end_date:
            if "trade_date" in query:
                query["trade_date"]["$lte"] = end_date
            else:
                query["trade_date"] = {"$lte": end_date}

        cursor = collection.find(query).sort("trade_date", 1)
        return await cursor.to_list(length=None)
