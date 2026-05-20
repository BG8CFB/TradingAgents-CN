"""
Tushare 财务数据编排模块

流程：Provider.get_financial_data() → Adapter.adapt_financial() → 批量 upsert MongoDB
"""
import asyncio
import logging
from typing import Any, Dict, List

from pymongo import UpdateOne

from app.data.schema.collections import get_collection_name
from app.utils.time_utils import now_utc

logger = logging.getLogger(__name__)


class TushareFinancialSync:
    """Tushare 财务数据同步编排"""

    def __init__(self, adapter):
        self.adapter = adapter
        self.provider = adapter.provider

    async def sync_financial(
        self, symbol: str, start_date: str = None, end_date: str = None,
    ) -> Dict[str, Any]:
        """
        同步单只股票的财务数据

        Args:
            symbol: 股票代码（6位）
            start_date: 开始日期 YYYY-MM-DD（未使用，保留接口兼容）
            end_date: 结束日期 YYYY-MM-DD（未使用，保留接口兼容）

        Returns:
            同步统计
        """
        stats = {"symbol": symbol, "saved": 0, "errors": 0}

        # 1. 获取原始数据 — Provider 签名仅 (symbol)
        raw_df = await self.provider.get_financial_data(symbol)
        if raw_df is None or raw_df.empty:
            logger.warning("Tushare 财务数据为空: %s", symbol)
            return stats

        # 2. 逐行转换并写入
        try:
            from app.core.database import get_database
            db = await get_database()
        except Exception as e:
            logger.error("无法连接数据库: %s", e)
            return stats

        collection_name = get_collection_name("CN", "financial")
        collection = db[collection_name]

        ops: List[UpdateOne] = []
        for _, row in raw_df.iterrows():
            schema = self.adapter.adapt_financial(row)
            if schema is None:
                continue

            doc = schema.to_db_doc()
            if not doc.get("symbol") or not doc.get("report_period"):
                continue

            filter_doc = {
                "symbol": doc["symbol"],
                "report_period": doc["report_period"],
            }
            if doc.get("statement_type"):
                filter_doc["statement_type"] = doc["statement_type"]

            doc["data_source"] = "tushare"
            doc["updated_at"] = now_utc().isoformat()

            ops.append(UpdateOne(filter_doc, {"$set": doc}, upsert=True))

            if len(ops) >= 200:
                saved = await self._bulk_write_async(collection, ops)
                stats["saved"] += saved
                ops = []

        if ops:
            saved = await self._bulk_write_async(collection, ops)
            stats["saved"] += saved

        logger.info("Tushare 财务同步完成: %s %d 条", symbol, stats["saved"])
        return stats

    @staticmethod
    async def _bulk_write_async(collection, ops) -> int:
        """异步批量写入"""
        try:
            result = await collection.bulk_write(ops, ordered=False)
            return result.upserted_count + result.modified_count
        except Exception as e:
            logger.error("批量写入失败: %s", e)
            return 0
