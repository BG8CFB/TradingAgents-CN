"""
Tushare 财务数据编排模块

流程：Provider.get_financial_data() → Adapter.adapt_financial() → 批量 upsert MongoDB
"""
import asyncio
import logging
from typing import Any, Dict, List

from pymongo import UpdateOne

from app.core.database import get_mongo_db_sync
from app.data.schema.collections import get_collection_name
from app.utils.time_utils import now_utc

logger = logging.getLogger(__name__)


class TushareFinancialSync:
    """Tushare 财务数据同步编排"""

    def __init__(self, adapter):
        self.adapter = adapter
        self.provider = adapter.provider

    async def sync_financial(
        self, symbol: str, start_date: str = None, end_date: str = None
    ) -> Dict[str, Any]:
        """
        同步单只股票的财务数据

        Args:
            symbol: 股票代码（6位）
            start_date: 开始日期 YYYY-MM-DD
            end_date: 结束日期 YYYY-MM-DD

        Returns:
            同步统计
        """
        stats = {"symbol": symbol, "saved": 0, "errors": 0}

        # 1. 获取原始数据
        raw_df = await self.provider.get_financial_data(symbol, start_date, end_date)
        if raw_df is None or raw_df.empty:
            logger.warning(f"Tushare 财务数据为空: {symbol}")
            return stats

        # 2. 逐行转换并写入
        db = get_mongo_db_sync()
        collection_name = get_collection_name("CN", "financial")
        collection = db[collection_name]

        ops = []
        for _, row in raw_df.iterrows():
            schema = self.adapter.adapt_financial(row)
            if schema is None:
                continue

            doc = schema.to_db_doc()
            if not doc.get("symbol") or not doc.get("report_period"):
                continue

            ops.append(
                UpdateOne(
                    {
                        "symbol": doc["symbol"],
                        "report_period": doc["report_period"],
                        "data_source": "tushare",
                    },
                    {"$set": doc},
                    upsert=True,
                )
            )

            if len(ops) >= 200:
                saved = await asyncio.to_thread(self._bulk_write, collection, ops)
                stats["saved"] += saved
                ops = []

        if ops:
            saved = await asyncio.to_thread(self._bulk_write, collection, ops)
            stats["saved"] += saved

        logger.info(f"Tushare 财务同步完成: {symbol} {stats['saved']} 条")
        return stats

    @staticmethod
    def _bulk_write(collection, ops) -> int:
        try:
            result = collection.bulk_write(ops, ordered=False)
            return result.upserted_count + result.modified_count
        except Exception as e:
            logger.error(f"批量写入失败: {e}")
            return 0
