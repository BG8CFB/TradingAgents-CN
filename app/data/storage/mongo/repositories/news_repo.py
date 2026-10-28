"""新闻公告仓储。"""

from typing import Dict, List, Optional

from pymongo import UpdateOne

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name
from app.data.storage.mongo.bulk_utils import batched_bulk_write


class NewsRepo:

    async def upsert_many(self, records: List[Dict], market: str) -> int:
        if not records:
            return 0
        db = get_motor_db()
        coll = db[get_collection_name("news", market)]
        ops = []
        for rec in records:
            ch = rec.get("content_hash")
            if not ch:
                continue
            ops.append(UpdateOne(
                {"content_hash": ch}, {"$set": rec}, upsert=True
            ))
        if not ops:
            return 0
        return await batched_bulk_write(coll, ops)

    async def get_by_symbol(
        self, symbol: str, market: str, limit: int = 20
    ) -> List[Dict]:
        db = get_motor_db()
        coll = db[get_collection_name("news", market)]
        cursor = coll.find(
            {"symbol": symbol}, {"_id": 0}
        ).sort("publish_time", -1).limit(limit)
        return await cursor.to_list(length=None)

    async def get_by_symbol_and_range(
        self, symbol: str, market: str,
        start_date: str, end_date: str, limit: int = 100,
    ) -> List[Dict]:
        """按发布时间区间读取个股新闻（publish_time 字符串同格式下字典序即时间序）。"""
        db = get_motor_db()
        coll = db[get_collection_name("news", market)]
        query: Dict = {"symbol": symbol}
        if start_date:
            query["publish_time"] = {"$gte": start_date}
        if end_date:
            query.setdefault("publish_time", {})
            query["publish_time"]["$lte"] = end_date
        cursor = coll.find(query, {"_id": 0}).sort("publish_time", -1)
        if limit:
            cursor = cursor.limit(limit)
        return await cursor.to_list(length=None)

    async def get_all(self, market: str, limit: int = 100) -> List[Dict]:
        db = get_motor_db()
        coll = db[get_collection_name("news", market)]
        # H6 修复：coll.find({"_id": 0}) 中 {"_id": 0} 是 filter 而非 projection。
        # _id 是 ObjectId，永远不等于 0，查询实际上返回空结果。
        cursor = coll.find({}, {"_id": 0}).sort("publish_time", -1)
        if limit:
            cursor = cursor.limit(limit)
        return await cursor.to_list(length=None)

    async def count_by_market(self, market: str) -> int:
        db = get_motor_db()
        coll = db[get_collection_name("news", market)]
        return await coll.count_documents({})

    async def get_updated_since(
        self, market: str, since: Optional[str], limit: int = 200,
        projection: Optional[Dict] = None,
    ) -> List[Dict]:
        """按 updated_at 升序读取增量新闻（知识库索引扫描用，数据层内部消费）。

        since 为空返回全量（按 updated_at 升序），供全量重建。
        """
        db = get_motor_db()
        coll = db[get_collection_name("news", market)]
        query: Dict = {}
        if since:
            query["updated_at"] = {"$gt": since}
        cursor = coll.find(query, projection or {"_id": 0}).sort("updated_at", 1).limit(limit)
        return await cursor.to_list(length=None)

    async def latest_publish_time(self, market: str) -> Optional[str]:
        """市场内最新一条新闻的发布时间（语料概览用）。"""
        db = get_motor_db()
        coll = db[get_collection_name("news", market)]
        doc = await coll.find_one(
            {"publish_time": {"$ne": None}},
            {"_id": 0, "publish_time": 1},
            sort=[("publish_time", -1)],
        )
        return (doc or {}).get("publish_time")
