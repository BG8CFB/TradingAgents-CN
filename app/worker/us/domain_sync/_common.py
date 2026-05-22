"""美股域同步通用辅助函数。"""

import logging
import time
from typing import Any, Callable, Dict, List, Optional

from app.data.sources.us import get_us_provider, get_us_adapter
from app.data.storage.mongo.collections import get_collection_name

logger = logging.getLogger(__name__)


async def sync_domain(
    domain: str,
    provider_method: str,
    adapter_method: str,
    provider_kwargs_fn: Optional[Callable] = None,
    filter_fields: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """通用美股域同步。"""
    from app.data.core.registry.capability import CapabilityRegistry
    from app.data.core.registry.priority import PriorityConfig
    from pymongo import UpdateOne
    from app.core.database import get_mongo_db_sync

    start = time.time()
    registry = CapabilityRegistry()
    priority = PriorityConfig()
    sources = registry.get_ordered_sources(
        "US", domain,
        user_priority=await priority.get_priority("US", domain),
    )

    for source_name in sources:
        provider = get_us_provider(source_name)
        adapter = get_us_adapter(source_name)
        if not provider or not adapter:
            continue

        try:
            kwargs = provider_kwargs_fn() if provider_kwargs_fn else {}
            raw = await getattr(provider, provider_method)(**kwargs)
            if raw is None:
                continue
            if hasattr(raw, "empty") and raw.empty:
                continue

            records = getattr(adapter, adapter_method)(raw)
            if not records:
                continue

            docs = [r.to_db_doc() for r in records]
            db = get_mongo_db_sync()
            col = db[get_collection_name(domain, "US")]

            fields = filter_fields or ["symbol"]
            ops = []
            for d in docs:
                filt = {f: d[f] for f in fields if f in d and d[f] is not None}
                if filt:
                    ops.append(UpdateOne(filt, {"$set": d}, upsert=True))

            if ops:
                col.bulk_write(ops, ordered=False)

            elapsed = int((time.time() - start) * 1000)
            logger.info(f"US {domain} 同步完成: {len(ops)} 条, 源={source_name}, 耗时={elapsed}ms")
            return {
                "domain": domain, "success": True, "source": source_name,
                "records": len(ops), "duration_ms": elapsed,
            }
        except Exception as e:
            logger.warning(f"US {domain} 源 {source_name} 失败: {e}")
            continue

    elapsed = int((time.time() - start) * 1000)
    return {"domain": domain, "success": False, "error": "所有数据源失败", "duration_ms": elapsed}
