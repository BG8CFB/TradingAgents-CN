"""因子分仓储 — L0 批算结果读写。"""

from typing import Dict, List, Optional
from uuid import uuid4

from pymongo import DeleteOne, UpdateOne

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name
from app.data.storage.mongo.bulk_utils import batched_bulk_write
from app.data.storage.mongo.repositories.key_spec import build_filter


class FactorScoresRepo:

    async def replace_complete_date(self, records: List[Dict], market: str,
                                    trade_date: str) -> Dict[str, int]:
        """发布一次完整计算后，精准清理该日期已被剔除的旧股票。

        与可容忍部分成功的 upsert_many 不同：任一写批失败立即上抛，不清理
        旧行。逐行批次标记核验成功后才删除开始时看见的排除行，且用版本
        条件防止删除被并发更新过的记录。不是跨文档原子快照/事务。
        调用方必须确认输入是成功完整计算（不是分页或失败后的部分结果）。
        """
        if not trade_date:
            raise ValueError("完整因子批次必须提供 trade_date")
        symbols = set()
        for record in records:
            build_filter("factor_scores", record)  # 缺主键不能静默跳过
            symbol = record["symbol"]
            if (not isinstance(symbol, str) or not symbol
                    or record["trade_date"] != trade_date
                    or record.get("market", market) != market
                    or symbol in symbols):
                raise ValueError("完整因子批次必须是同市场同日期且股票主键唯一")
            symbols.add(symbol)

        db = get_motor_db()
        coll = db[get_collection_name("factor_scores", market)]
        excluded = await coll.find(
            {"trade_date": trade_date, "symbol": {"$nin": sorted(symbols)}},
            {"_id": 1, "updated_at": 1, "_calculation_id": 1},
        ).to_list(length=None)
        calculation_id = uuid4().hex
        ops = [UpdateOne(build_filter("factor_scores", record),
                         {"$set": {**record, "_calculation_id": calculation_id}},
                         upsert=True) for record in records]
        # 不使用 batched_bulk_write：它容忍中间批失败，不适合完整快照清理。
        for offset in range(0, len(ops), 500):
            await coll.bulk_write(ops[offset:offset + 500], ordered=False)
        written = await coll.count_documents(
            {"trade_date": trade_date, "_calculation_id": calculation_id})
        if written != len(records):
            raise RuntimeError("因子完整批次校验失败，保留旧行等待重试")

        removals = []
        for old in excluded:
            guard = {"_id": old["_id"], "trade_date": trade_date}
            for field in ("updated_at", "_calculation_id"):
                guard[field] = ({"$exists": True, "$eq": old[field]}
                                if field in old else {"$exists": False})
            removals.append(DeleteOne(guard))
        removed = 0
        for offset in range(0, len(removals), 500):
            result = await coll.bulk_write(removals[offset:offset + 500], ordered=False)
            removed += result.deleted_count
        return {"written": written, "removed": removed}

    async def upsert_many(self, records: List[Dict], market: str) -> int:
        """按 (symbol, trade_date) 幂等覆盖写入；缺唯一键的记录跳过。"""
        if not records:
            return 0
        db = get_motor_db()
        coll = db[get_collection_name("factor_scores", market)]
        ops = []
        for rec in records:
            try:
                filter_doc = build_filter("factor_scores", rec)
            except KeyError:
                continue
            ops.append(UpdateOne(filter_doc, {"$set": rec}, upsert=True))
        if not ops:
            return 0
        return await batched_bulk_write(coll, ops)

    async def get_by_symbol_and_range(
        self, symbol: str, market: str, start_date: str, end_date: str
    ) -> List[Dict]:
        db = get_motor_db()
        coll = db[get_collection_name("factor_scores", market)]
        cursor = coll.find(
            {"symbol": symbol, "trade_date": {"$gte": start_date, "$lte": end_date}},
            {"_id": 0},
        ).sort("trade_date", -1)
        return await cursor.to_list(length=None)

    async def get_latest_trade_date(self, market: str) -> Optional[str]:
        db = get_motor_db()
        coll = db[get_collection_name("factor_scores", market)]
        doc = await coll.find_one({}, {"trade_date": 1, "_id": 0},
                                  sort=[("trade_date", -1)])
        return doc.get("trade_date") if doc else None

    async def get_all_by_date(self, market: str, trade_date: str,
                              projection: Optional[Dict] = None) -> List[Dict]:
        db = get_motor_db()
        coll = db[get_collection_name("factor_scores", market)]
        cursor = coll.find({"trade_date": trade_date}, projection or {"_id": 0})
        return await cursor.to_list(length=None)
