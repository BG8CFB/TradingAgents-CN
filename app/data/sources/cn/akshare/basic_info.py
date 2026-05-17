"""
AKShare 基础信息编排模块

流程：Provider.get_stock_list() → Adapter.adapt_basic_info() → 批量 upsert MongoDB
"""
import asyncio
import logging
from typing import Any, Dict, List

from pymongo import UpdateOne

from app.core.database import get_mongo_db_sync
from app.data.schema.collections import get_collection_name
from app.utils.time_utils import now_utc

logger = logging.getLogger(__name__)


class AKShareBasicInfoSync:
    """AKShare 基础信息同步编排"""

    def __init__(self, adapter):
        self.adapter = adapter
        self.provider = adapter.provider

    async def sync_all(self, force: bool = False, job_id: str = None) -> Dict[str, Any]:
        stats = {
            "total": 0,
            "success": 0,
            "errors": 0,
            "started_at": now_utc().isoformat(),
        }

        raw_df = await self.provider.get_stock_list()
        if raw_df is None or raw_df.empty:
            logger.error("AKShare 返回空股票列表")
            stats["error"] = "AKShare returned empty stock list"
            return stats

        stats["total"] = len(raw_df)
        logger.info(f"AKShare 基础信息同步开始: {stats['total']} 只股票")

        schemas = self.adapter.adapt_basic_info_batch(raw_df)

        db = get_mongo_db_sync()
        collection_name = get_collection_name("CN", "basic_info")
        collection = db[collection_name]

        batch_size = 1000
        ops = []
        success = 0

        for schema in schemas:
            doc = schema.to_db_doc()
            if not doc.get("symbol"):
                continue

            ops.append(
                UpdateOne(
                    {"symbol": doc["symbol"], "data_source": "akshare"},
                    {"$set": doc},
                    upsert=True,
                )
            )

            if len(ops) >= batch_size:
                success += await asyncio.to_thread(self._bulk_write, collection, ops)
                ops = []

        if ops:
            success += await asyncio.to_thread(self._bulk_write, collection, ops)

        stats["success"] = success
        stats["errors"] = stats["total"] - success
        stats["finished_at"] = now_utc().isoformat()
        logger.info(f"AKShare 基础信息同步完成: {success}/{stats['total']}")
        return stats

    @staticmethod
    def _bulk_write(collection, ops) -> int:
        try:
            result = collection.bulk_write(ops, ordered=False)
            return result.upserted_count + result.modified_count
        except Exception as e:
            logger.error(f"批量写入失败: {e}")
            return 0
