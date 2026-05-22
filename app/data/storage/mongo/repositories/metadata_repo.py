"""元数据仓储 — sync_checkpoints / sync_events / source_health / system_configs。"""

from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.data.storage.mongo.client import get_motor_db


class MetadataRepo:
    """统一元数据仓储，操作 4 个元数据集合。"""

    # ── sync_checkpoints ──

    async def get_checkpoint(self, market: str, domain: str, source: str) -> Optional[Dict]:
        db = get_motor_db()
        coll = db["sync_checkpoints"]
        return await coll.find_one(
            {"market": market, "domain": domain, "source": source},
            {"_id": 0},
        )

    async def update_checkpoint(
        self, market: str, domain: str, source: str,
        last_sync_date: str, record_count: int, status: str = "success"
    ) -> None:
        db = get_motor_db()
        coll = db["sync_checkpoints"]
        await coll.update_one(
            {"market": market, "domain": domain, "source": source},
            {
                "$set": {
                    "last_sync_date": last_sync_date,
                    "last_sync_time": datetime.now(timezone.utc).isoformat(),
                    "status": status,
                    "record_count": record_count,
                }
            },
            upsert=True,
        )

    # ── sync_events ──

    async def insert_event(self, event: Dict) -> None:
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
        return await cursor.to_list(length=None)

    # ── source_health ──

    async def get_health(self, market: str, source: str, domain: str) -> Optional[Dict]:
        db = get_motor_db()
        coll = db["source_health"]
        return await coll.find_one(
            {"market": market, "source": source, "domain": domain},
            {"_id": 0},
        )

    async def upsert_health(self, market: str, source: str, domain: str, data: Dict) -> None:
        db = get_motor_db()
        coll = db["source_health"]
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        await coll.update_one(
            {"market": market, "source": source, "domain": domain},
            {"$set": data},
            upsert=True,
        )

    async def get_all_health(self, market: str) -> List[Dict]:
        db = get_motor_db()
        coll = db["source_health"]
        cursor = coll.find({"market": market}, {"_id": 0})
        return await cursor.to_list(length=None)

    # ── system_configs ──

    async def get_config(self, config_type: str, market: str, domain: Optional[str] = None) -> Optional[Dict]:
        db = get_motor_db()
        coll = db["system_configs"]
        query = {"config_type": config_type, "market": market}
        if domain:
            query["domain"] = domain
        return await coll.find_one(query, {"_id": 0})

    async def upsert_config(self, config_type: str, market: str, domain: str, value: Dict, updated_by: str = "system") -> None:
        db = get_motor_db()
        coll = db["system_configs"]
        await coll.update_one(
            {"config_type": config_type, "market": market, "domain": domain},
            {
                "$set": {
                    "value": value,
                    "updated_by": updated_by,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            },
            upsert=True,
        )
