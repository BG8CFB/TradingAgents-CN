"""通用 Repository — 用于新增数据域（北向资金、外资持仓、限售解禁等）"""

import logging
from typing import Dict, List, Optional

from app.data.storage.mongo.collections import get_collection_name
from app.data.storage.mongo.client import get_motor_db

logger = logging.getLogger(__name__)

# 各域使用的日期字段名
_DATE_FIELD_MAP = {
    "share_unlock": "end_date",
    "pledge": "end_date",
    # 业绩预告/快报/分红的日期字段为 end_date（非 trade_date）
    "forecast": "end_date",
    "express": "end_date",
    "dividend": "end_date",
    # 公告日期字段为 ann_date（非 trade_date）
    "announcement": "ann_date",
}


class GenericRepo:
    """通用数据仓库，按 domain 名自动映射到 MongoDB 集合。"""

    def __init__(self, domain: str):
        self.domain = domain

    def _get_collection(self, market: str):
        db = get_motor_db()
        return db[get_collection_name(self.domain, market)]

    async def upsert_many(self, records: List[dict], market: str) -> int:
        """批量 upsert 写入。按 symbol + trade_date（或 ts_code + end_date）去重。"""
        if not records:
            return 0
        coll = self._get_collection(market)

        # 确定主键字段
        sample = records[0]
        if "trade_date" in sample and "symbol" in sample:
            key_fields = ["symbol", "trade_date"]
        elif "trade_date" in sample and "ts_code" in sample:
            key_fields = ["ts_code", "trade_date"]
        elif "end_date" in sample and "ts_code" in sample:
            key_fields = ["ts_code", "end_date"]
        elif "ann_date" in sample and "ts_code" in sample:
            key_fields = ["ts_code", "ann_date"]
        elif "symbol" in sample:
            key_fields = ["symbol"]
        elif "ts_code" in sample:
            key_fields = ["ts_code"]
        else:
            key_fields = []

        count = 0
        for record in records:
            try:
                # 清理 _id 字段避免冲突
                record.pop("_id", None)

                if key_fields:
                    filter_query = {k: record.get(k) for k in key_fields if k in record}
                    if filter_query:
                        await coll.update_one(
                            filter_query,
                            {"$set": record},
                            upsert=True,
                        )
                    else:
                        await coll.insert_one(record)
                else:
                    await coll.insert_one(record)
                count += 1
            except Exception as e:
                logger.debug(f"写入 {self.domain}/{market} 失败: {e}")
                continue

        if count > 0:
            logger.info(f"写入 {self.domain}/{market}: {count} 条")
        return count

    async def count(self, market: str) -> int:
        coll = self._get_collection(market)
        return await coll.count_documents({})

    def _date_field(self) -> str:
        """获取当前域使用的日期字段名。"""
        return _DATE_FIELD_MAP.get(self.domain, "trade_date")

    async def get_by_symbol_and_range(
        self, symbol: str, market: str, start_date: str, end_date: str,
    ) -> List[Dict]:
        """按 symbol + 日期范围查询。"""
        coll = self._get_collection(market)
        date_col = self._date_field()
        query = {
            "symbol": symbol,
            date_col: {"$gte": start_date, "$lte": end_date},
        }
        cursor = coll.find(query, {"_id": 0}).sort(date_col, -1)
        return await cursor.to_list(length=None)

    async def get_by_date_range(
        self, market: str, start_date: str, end_date: str, limit: int = 1000,
    ) -> List[Dict]:
        """按日期范围查询全部数据（用于 __all__ 模式）。"""
        coll = self._get_collection(market)
        date_col = self._date_field()
        query = {date_col: {"$gte": start_date, "$lte": end_date}}
        cursor = coll.find(query, {"_id": 0}).sort(date_col, -1).limit(limit)
        return await cursor.to_list(length=None)

    async def get_by_symbol(
        self, symbol: str, market: str, limit: int = 50,
    ) -> List[Dict]:
        """按 symbol 查询最新 N 条。"""
        coll = self._get_collection(market)
        date_col = self._date_field()
        cursor = coll.find(
            {"symbol": symbol}, {"_id": 0}
        ).sort(date_col, -1).limit(limit)
        return await cursor.to_list(length=None)
