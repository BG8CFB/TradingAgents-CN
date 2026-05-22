"""港股基础信息同步 — 使用新架构。"""

import logging
from typing import Optional

from app.data.sources.hk import get_hk_provider, get_hk_adapter
from app.data.storage.mongo.collections import get_collection_name

logger = logging.getLogger(__name__)


async def sync_basic_info() -> dict:
    """同步港股基础信息。"""
    import time
    import asyncio
    from app.data.core.registry.capability import CapabilityRegistry
    from app.data.core.registry.priority import PriorityConfig
    from pymongo import UpdateOne
    from app.core.database import get_mongo_db_sync

    start = time.time()
    registry = CapabilityRegistry()
    priority = PriorityConfig()
    sources = registry.get_ordered_sources("HK", "basic_info", user_priority=await priority.get_priority("HK", "basic_info"))

    for source_name in sources:
        provider = get_hk_provider(source_name)
        adapter = get_hk_adapter(source_name)
        if not provider or not adapter:
            continue
        try:
            raw = await provider.get_stock_list()
            if raw is None or raw.empty:
                continue

            records = adapter.adapt_basic_info(raw)
            if not records:
                continue

            docs = [r.to_db_doc() for r in records if r.symbol]
            db = get_mongo_db_sync()
            col = db[get_collection_name("basic_info", "HK")]
            ops = [UpdateOne({"symbol": d["symbol"]}, {"$set": d}, upsert=True) for d in docs if d.get("symbol")]
            if ops:
                col.bulk_write(ops, ordered=False)

            elapsed = int((time.time() - start) * 1000)
            logger.info(f"HK basic_info 同步完成: {len(ops)} 条, 源={source_name}, 耗时={elapsed}ms")
            return {"domain": "basic_info", "success": True, "source": source_name, "records": len(ops), "duration_ms": elapsed}
        except Exception as e:
            logger.warning(f"HK basic_info 源 {source_name} 失败: {e}")
            continue

    return {"domain": "basic_info", "success": False, "error": "所有数据源失败", "duration_ms": int((time.time() - start) * 1000)}
