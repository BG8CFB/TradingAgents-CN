"""
Tushare 行情数据编排模块

流程：Provider.get_daily_quotes() → Adapter.adapt_daily_quote() → 批量 upsert MongoDB
"""

import asyncio
import logging
from typing import Any, Dict, List

from pymongo import ReplaceOne

from app.core.database import get_mongo_db_sync
from app.data.schema.collections import get_collection_name
from app.utils.time_utils import now_utc

logger = logging.getLogger(__name__)


class TushareQuotesSync:
    """Tushare 行情数据同步编排"""

    def __init__(self, adapter):
        self.adapter = adapter
        self.provider = adapter.provider

    async def sync_daily(
        self, symbol: str, start_date: str, end_date: str
    ) -> Dict[str, Any]:
        """
        同步单只股票的日线数据

        Args:
            symbol: 股票代码（6位）
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD

        Returns:
            同步统计
        """
        stats = {"symbol": symbol, "saved": 0, "errors": 0}

        # 1. 获取原始数据
        raw_df = await self.provider.get_daily_quotes(symbol, start_date, end_date)
        if raw_df is None or raw_df.empty:
            logger.warning(f"Tushare 日线数据为空: {symbol}")
            return stats

        # 2. 批量转换
        schemas = self.adapter.adapt_daily_quote_batch(raw_df)

        # 3. 批量 upsert
        db = get_mongo_db_sync()
        collection_name = get_collection_name("CN", "daily_quotes")
        collection = db[collection_name]

        batch_size = 200
        ops = []

        for schema in schemas:
            doc = schema.to_db_doc()
            if not doc.get("symbol") or not doc.get("trade_date"):
                continue

            filter_doc = {
                "symbol": doc["symbol"],
                "trade_date": doc["trade_date"],
                "data_source": doc["data_source"],
                "period": doc.get("period", "daily"),
            }
            ops.append(ReplaceOne(filter=filter_doc, replacement=doc, upsert=True))

            if len(ops) >= batch_size:
                saved = await asyncio.to_thread(self._bulk_write, collection, ops)
                stats["saved"] += saved
                ops = []

        if ops:
            saved = await asyncio.to_thread(self._bulk_write, collection, ops)
            stats["saved"] += saved

        logger.info(f"Tushare 日线同步完成: {symbol} {stats['saved']} 条")
        return stats

    @staticmethod
    def _bulk_write(collection, ops) -> int:
        """同步执行批量写入"""
        try:
            result = collection.bulk_write(ops, ordered=False)
            return result.upserted_count + result.modified_count
        except Exception as e:
            logger.error(f"批量写入失败: {e}")
            return 0
