"""港股基础信息同步"""
import logging
from typing import Any, Dict, Optional

from app.data.processor.capability_registry import CapabilityRegistry
from app.data.processor.fallback_router import FallbackRouter
from app.data.schema.base import normalize_symbol
from app.data.schema.collections import get_collection_name
from app.worker.cn.domain_sync.base_domain_sync import BaseDomainSync, DomainSyncResult

logger = logging.getLogger(__name__)


class HKBasicInfoSync(BaseDomainSync):
    domain = "basic_info"
    description = "港股基础信息同步"

    def __init__(self, router: Optional[FallbackRouter] = None):
        super().__init__(router=router)

    async def sync(self, **kwargs) -> DomainSyncResult:
        start = self._now_ms()
        try:
            registry = CapabilityRegistry(market="HK")
            sources = registry.get_ordered_sources("basic_info")

            for source_name in sources:
                provider = self._get_provider(source_name)
                if not provider:
                    continue

                try:
                    df = await provider.get_stock_list()
                    if df is None or df.empty:
                        continue

                    records = self._to_records(df)
                    written = await self._write_to_mongo(records)

                    return DomainSyncResult(
                        domain=self.domain,
                        success=True,
                        source=source_name,
                        records_synced=written,
                        duration_ms=self._elapsed_ms(start),
                    )
                except Exception as e:
                    logger.warning(f"HK basic_info {source_name} 失败: {e}")
                    continue

            return DomainSyncResult(
                domain=self.domain, success=False,
                error="所有数据源失败", duration_ms=self._elapsed_ms(start),
            )
        except Exception as e:
            return DomainSyncResult(
                domain=self.domain, success=False,
                error=str(e), duration_ms=self._elapsed_ms(start),
            )

    def _get_provider(self, source_name: str):
        if source_name == "akshare_hk":
            from app.data.sources.hk.akshare_hk.provider import AKShareHKProvider
            return AKShareHKProvider()
        elif source_name == "yfinance_hk":
            from app.data.sources.hk.yfinance_hk.provider import YFinanceHKProvider
            return YFinanceHKProvider()
        return None

    def _to_records(self, df) -> list:
        records = []
        for _, row in df.iterrows():
            d = row.to_dict()
            # 尝试提取 symbol
            for key in ["代码", "代码", "symbol", "code"]:
                if key in d and d[key]:
                    d["symbol"] = str(d[key]).strip()
                    break
            if "symbol" in d:
                d["symbol"] = normalize_symbol(d["symbol"], "HK")
            records.append(d)
        return records

    async def _write_to_mongo(self, records: list) -> int:
        from pymongo import UpdateOne
        from app.core.database import get_mongo_db_sync
        db = get_mongo_db_sync()
        col_name = get_collection_name("HK", "basic_info")
        col = db[col_name]
        ops = []
        for r in records:
            sym = r.get("symbol", "")
            if not sym:
                continue
            ops.append(UpdateOne({"symbol": sym}, {"$set": r}, upsert=True))
        if ops:
            col.bulk_write(ops)
        return len(ops)

    @staticmethod
    def _now_ms():
        import time
        return int(time.time() * 1000)

    @staticmethod
    def _elapsed_ms(start):
        import time
        return int(time.time() * 1000) - start
