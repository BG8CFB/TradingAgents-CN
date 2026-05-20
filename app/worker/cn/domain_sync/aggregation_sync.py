"""周线/月线聚合同步"""

import logging
import time
from typing import Any, Dict, List, Optional

from .base_domain_sync import BaseDomainSync, DomainSyncResult
from app.data.processor.aggregation import aggregate_period
from app.data.processor.fallback_router import FallbackRouter
from app.data.schema.collections import get_collection_name

logger = logging.getLogger(__name__)


class AggregationSync(BaseDomainSync):
    """周线/月线聚合（依赖日线数据）"""

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
            # 从 MongoDB 读取日线数据
            daily_records = await self._read_daily_quotes(
                symbol, start_date, end_date,
            )

            if not daily_records:
                return DomainSyncResult(
                    domain=self.domain, success=False,
                    error="无日线数据可聚合",
                    duration_ms=int((time.monotonic() - start) * 1000),
                )

            # 聚合
            aggregated = aggregate_period(daily_records, period=period)

            if not aggregated:
                return DomainSyncResult(
                    domain=self.domain, success=False,
                    error="聚合结果为空",
                    duration_ms=int((time.monotonic() - start) * 1000),
                )

            # 写入（period 字段区分日线/周线/月线）
            records = await self._write_to_mongo(
                aggregated, "aggregation",
                filter_fields=["symbol", "trade_date", "period"],
            )

            duration_ms = int((time.monotonic() - start) * 1000)
            result = DomainSyncResult(
                domain=self.domain,
                success=True,
                source="aggregation",
                records_synced=records,
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
        """从 MongoDB 读取日线数据"""
        try:
            from app.core.database import get_database
            db = await get_database()
        except Exception:
            return []

        collection_name = get_collection_name("CN", "daily_quotes")
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
