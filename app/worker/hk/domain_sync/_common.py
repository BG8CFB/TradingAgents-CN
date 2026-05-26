"""港股域同步通用辅助函数。"""

import logging
import time
from typing import Any, Callable, Dict, List, Optional

from app.data.sources.hk import get_hk_provider, get_hk_adapter
from app.data.storage.mongo.collections import get_collection_name

logger = logging.getLogger(__name__)


async def sync_domain(
    domain: str,
    provider_method: str,
    adapter_method: str,
    provider_kwargs_fn: Optional[Callable] = None,
    filter_fields: Optional[List[str]] = None,
    default_filter_fields: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """通用港股域同步。

    Args:
        domain: 数据域名称
        provider_method: Provider 上的方法名
        adapter_method: Adapter 上的方法名
        provider_kwargs_fn: 可选的函数，返回传递给 provider 方法的 kwargs
        filter_fields: MongoDB upsert 过滤字段
        default_filter_fields: 默认过滤字段（symbol + domain 特定字段）
    """
    from app.data.core.registry.capability import CapabilityRegistry
    from app.data.core.registry.priority import PriorityConfig
    from pymongo import UpdateOne
    from app.core.database import get_database

    start = time.time()
    registry = CapabilityRegistry()
    priority = PriorityConfig()
    sources = registry.get_ordered_sources(
        "HK", domain,
        user_priority=await priority.get_priority("HK", domain),
    )

    for source_name in sources:
        provider = get_hk_provider(source_name)
        adapter = get_hk_adapter(source_name)
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
            db = await get_database()
            collection = db[get_collection_name(domain, "HK")]

            fields = filter_fields or default_filter_fields or ["symbol"]
            ops = []
            for d in docs:
                filt = {f: d[f] for f in fields if f in d and d[f] is not None}
                if filt:
                    ops.append(UpdateOne(filt, {"$set": d}, upsert=True))

            if ops:
                await collection.bulk_write(ops, ordered=False)

            elapsed = int((time.time() - start) * 1000)
            logger.info(f"HK {domain} 同步完成: {len(ops)} 条, 源={source_name}, 耗时={elapsed}ms")
            return {
                "domain": domain, "success": True, "source": source_name,
                "records": len(ops), "duration_ms": elapsed,
            }
        except Exception as e:
            logger.warning(f"HK {domain} 源 {source_name} 失败: {e}")
            continue

    elapsed = int((time.time() - start) * 1000)
    return {"domain": domain, "success": False, "error": "所有数据源失败", "duration_ms": elapsed}
