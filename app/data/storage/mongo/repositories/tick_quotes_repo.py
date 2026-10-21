"""逐笔成交（tick）仓储 —— PRD FR-06 / 技术方案第六节第 6 步。"""

from typing import Dict, List, Optional

from pymongo import UpdateOne

from app.data.storage.mongo.bulk_utils import batched_bulk_write
from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name
from app.data.storage.mongo.repositories.key_spec import build_filter

_DOMAIN = "tick_quotes"


class TickQuotesRepo:
    """stock_tick_quotes 集合仓储。

    单版本覆盖语义：upsert filter 由 ``key_spec.build_filter`` 从
    ``index_definitions`` 的唯一键（symbol + trade_date + time_ms）自动派生，
    不含 data_source —— 备用源覆盖同自然键记录（与 daily_quotes 同规）。
    """

    async def upsert_many(self, records: List[Dict], market: str) -> int:
        if not records:
            return 0
        db = get_motor_db()
        coll = db[get_collection_name(_DOMAIN, market)]
        ops = []
        for rec in records:
            try:
                filter_doc = build_filter(_DOMAIN, rec)
            except KeyError:
                continue  # 缺少唯一键字段的记录跳过
            ops.append(UpdateOne(
                filter_doc,
                {"$set": rec},
                upsert=True,
            ))
        if not ops:
            return 0
        return await batched_bulk_write(coll, ops)

    async def get_by_symbol_and_range(
        self, symbol: str, market: str, start_date: str, end_date: str,
        limit: Optional[int] = None,
    ) -> List[Dict]:
        """按 symbol + trade_date 闭区间取 tick（time_ms 升序＝时间自然序）。

        ``limit`` 用于消费侧限制单次返回量：单日 tick 可达数十万条，
        无上限查询会打爆接口响应（技术方案 §7 O-2 的体量背景）。
        """
        db = get_motor_db()
        coll = db[get_collection_name(_DOMAIN, market)]
        query: Dict = {
            "symbol": symbol,
            "trade_date": {"$gte": start_date, "$lte": end_date},
        }
        cursor = coll.find(query, {"_id": 0}).sort("time_ms", 1)
        if limit:
            cursor = cursor.limit(int(limit))
        return await cursor.to_list(length=None)

    async def delete_before_date(self, market: str, cutoff_date: str) -> int:
        """删除 ``trade_date < cutoff_date`` 的分区（保留期清理 Job）。

        返回删除条数，供 Job 写入 ``sync_events`` 审计（PRD FR-06 规则 3：
        清理动作必须可审计，这也是不用 Mongo TTL 索引的原因，见 DD-03）。
        """
        db = get_motor_db()
        coll = db[get_collection_name(_DOMAIN, market)]
        result = await coll.delete_many({"trade_date": {"$lt": cutoff_date}})
        return int(getattr(result, "deleted_count", 0) or 0)

    async def count_by_date(self, market: str, trade_date: str) -> int:
        """单日已入库条数（写入量阈值与自检覆盖率用）。"""
        db = get_motor_db()
        coll = db[get_collection_name(_DOMAIN, market)]
        return int(await coll.count_documents({"trade_date": trade_date}))
