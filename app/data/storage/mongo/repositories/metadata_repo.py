"""元数据仓储 — sync_checkpoints / sync_events / source_health / system_configs。

命名迁移（source → data_source）兼容窗口约定：
- 写侧统一写 `data_source` 标准键（legacy `source` 键在已存在的文档上保留不删）；
- 读侧经 `_project_source_compat` 补齐双键：缺 `data_source` 用 `source` 补，
  缺 `source` 用 `data_source` 补，保证新旧消费方都能工作；
- upsert 匹配先按 `data_source` 再按 legacy `source` 双过滤尝试（不用 $or：
  模拟测试库与真实 Mongo 对 $or+upsert 派生插入文档的语义不一致）。
- 方法名与参数名（如 `source`）是调用方 API，不改；只有文档键是字段方言。
  窗口期结束后移除投影与 legacy 匹配（连同迁移脚本 scripts/rename_metadata_source_field.py）。
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.data.storage.mongo.client import get_motor_db


def _project_source_compat(doc: Optional[Dict]) -> Optional[Dict]:
    """兼容期读投影：data_source / source 双键互补，原键保留不删。"""
    if doc is None:
        return None
    ds, legacy = doc.get("data_source"), doc.get("source")
    if ds is None and legacy is not None:
        doc["data_source"] = legacy
    elif legacy is None and ds is not None:
        doc["source"] = ds
    return doc


class MetadataRepo:
    """统一元数据仓储，操作 4 个元数据集合。"""

    # ── sync_checkpoints ──

    async def get_checkpoint(self, market: str, domain: str, source: str) -> Optional[Dict]:
        db = get_motor_db()
        coll = db["sync_checkpoints"]
        doc = await coll.find_one(
            {
                "market": market,
                "domain": domain,
                "$or": [{"data_source": source}, {"source": source}],
            },
            {"_id": 0},
        )
        return _project_source_compat(doc)

    async def update_checkpoint(
        self, market: str, domain: str, source: str,
        last_sync_date: str, record_count: int, status: str = "success",
        duration_ms: Optional[int] = None,
        scope: Optional[str] = None,
        trigger: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> None:
        db = get_motor_db()
        coll = db["sync_checkpoints"]
        set_fields: Dict = {
            "market": market,
            "domain": domain,
            "data_source": source,
            "last_sync_date": last_sync_date,
            "last_sync_time": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "record_count": record_count,
        }
        if duration_ms is not None:
            set_fields["duration_ms"] = duration_ms
        if scope is not None:
            set_fields["scope"] = scope
        if trigger is not None:
            set_fields["trigger"] = trigger
        if symbol is not None:
            set_fields["symbol"] = symbol
        base = {"market": market, "domain": domain}
        result = await coll.update_one({**base, "data_source": source}, {"$set": set_fields})
        if result.matched_count == 0:
            # legacy 文档（只有 source 键）就地升级为双键，不另插新文档
            result = await coll.update_one({**base, "source": source}, {"$set": set_fields})
        if result.matched_count == 0:
            await coll.update_one(
                {**base, "data_source": source}, {"$set": set_fields}, upsert=True
            )

    async def get_all_checkpoints(
        self, market: str, domain: Optional[str] = None,
        trigger: Optional[str] = None,
    ) -> List[Dict]:
        """查询指定市场的所有同步检查点。

        trigger: 仅返回该触发类型的检查点（manual/scheduled），None=不过滤。
        """
        db = get_motor_db()
        coll = db["sync_checkpoints"]
        query: Dict = {"market": market}
        if domain:
            query["domain"] = domain
        if trigger:
            query["trigger"] = trigger
        cursor = coll.find(query, {"_id": 0}).sort("last_sync_time", -1)
        return [_project_source_compat(d) for d in await cursor.to_list(length=None)]

    # ── sync_events ──

    async def insert_event(self, event: Dict) -> None:
        # 兼容收口：尚未改到 data_source 的写入方（如一次性脚本）传 legacy
        # source 键时，在这里补标准键，保证入库事件双键齐全。
        if "data_source" not in event and event.get("source") is not None:
            event["data_source"] = event["source"]
        db = get_motor_db()
        coll = db["sync_events"]
        if "created_at" not in event:
            event["created_at"] = datetime.now(timezone.utc).isoformat()
        await coll.insert_one(event)

    async def get_events(
        self, market: str, domain: Optional[str] = None, limit: int = 50
    ) -> List[Dict]:
        db = get_motor_db()
        coll = db["sync_events"]
        query = {"market": market}
        if domain:
            query["domain"] = domain
        cursor = coll.find(query, {"_id": 0}).sort("created_at", -1).limit(limit)
        return [_project_source_compat(d) for d in await cursor.to_list(length=None)]

    # ── source_health ──

    async def get_health(self, market: str, source: str, domain: str) -> Optional[Dict]:
        db = get_motor_db()
        coll = db["source_health"]
        doc = await coll.find_one(
            {
                "market": market,
                "domain": domain,
                "$or": [{"data_source": source}, {"source": source}],
            },
            {"_id": 0},
        )
        return _project_source_compat(doc)

    async def upsert_health(self, market: str, source: str, domain: str, data: Dict) -> None:
        db = get_motor_db()
        coll = db["source_health"]
        data = {**data, "data_source": source, "updated_at": datetime.now(timezone.utc).isoformat()}
        base = {"market": market, "domain": domain}
        result = await coll.update_one({**base, "data_source": source}, {"$set": data})
        if result.matched_count == 0:
            result = await coll.update_one({**base, "source": source}, {"$set": data})
        if result.matched_count == 0:
            await coll.update_one({**base, "data_source": source}, {"$set": data}, upsert=True)

    async def get_all_health(self, market: str) -> List[Dict]:
        db = get_motor_db()
        coll = db["source_health"]
        cursor = coll.find({"market": market}, {"_id": 0})
        return [_project_source_compat(d) for d in await cursor.to_list(length=None)]

    # ── system_configs ──

    async def get_config(
        self,
        config_type: str,
        market: str,
        domain: Optional[str] = None,
        config_key: Optional[str] = None,
    ) -> Optional[Dict]:
        db = get_motor_db()
        coll = db["system_configs"]
        query = {"config_type": config_type, "market": market}
        if domain:
            query["domain"] = domain
        if config_key:
            query["config_key"] = config_key
        return await coll.find_one(query, {"_id": 0})

    async def upsert_config(
        self,
        config_type: str,
        market: str,
        domain: str,
        value: Dict,
        updated_by: str = "system",
        config_key: str = "default",
    ) -> None:
        db = get_motor_db()
        coll = db["system_configs"]
        await coll.update_one(
            {
                "config_type": config_type,
                "market": market,
                "domain": domain,
                "config_key": config_key,
            },
            {
                "$set": {
                    "value": value,
                    "config_key": config_key,
                    "updated_by": updated_by,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            },
            upsert=True,
        )
