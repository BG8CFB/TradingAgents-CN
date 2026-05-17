"""
港股 AKShare 按需缓存编排

流程：Provider → Adapter → Schema → MongoDB (按需写入)
"""
import asyncio
import logging
from typing import Any, Dict

from pymongo import UpdateOne

from app.core.database import get_mongo_db_sync
from app.data.schema.collections import get_collection_name

logger = logging.getLogger(__name__)


class AKShareHKOrchestrator:
    """港股 AKShare 按需缓存编排"""

    def __init__(self, adapter):
        self.adapter = adapter
        self.provider = adapter.provider

    async def warm_stock_info(self, symbol: str) -> bool:
        """预热单只港股基础信息"""
        try:
            raw_info = await self.provider.get_stock_basic_info(symbol)
            if raw_info is None:
                return False

            schema = self.adapter.adapt_basic_info(raw_info)
            if schema is None:
                return False

            doc = schema.to_db_doc()
            if not doc.get("symbol"):
                return False

            db = get_mongo_db_sync()
            collection_name = get_collection_name("HK", "basic_info")
            db[collection_name].update_one(
                {"symbol": doc["symbol"], "data_source": "akshare"},
                {"$set": doc},
                upsert=True,
            )
            logger.info(f"✅ [港股/AKShare] 基础信息预热成功: {symbol}")
            return True
        except Exception as e:
            logger.error(f"❌ [港股/AKShare] 基础信息预热失败: {symbol} - {e}")
            return False

    async def warm_daily_quotes(
        self, symbol: str, start_date: str, end_date: str
    ) -> int:
        """预热单只港股行情数据，返回写入条数"""
        try:
            raw_df = await self.provider.get_daily_quotes(symbol, start_date, end_date)
            if raw_df is None or raw_df.empty:
                return 0

            schemas = self.adapter.adapt_daily_quote_batch(raw_df)

            db = get_mongo_db_sync()
            collection_name = get_collection_name("HK", "daily_quotes")
            collection = db[collection_name]

            ops = []
            for schema in schemas:
                doc = schema.to_db_doc()
                if not doc.get("symbol") or not doc.get("trade_date"):
                    continue

                ops.append(
                    UpdateOne(
                        {
                            "symbol": doc["symbol"],
                            "trade_date": doc["trade_date"],
                            "data_source": "akshare",
                            "period": "daily",
                        },
                        {"$set": doc},
                        upsert=True,
                    )
                )

            if ops:
                result = await asyncio.to_thread(
                    collection.bulk_write, ops, False
                )
                saved = result.upserted_count + result.modified_count
                logger.info(f"✅ [港股/AKShare] 行情预热: {symbol} {saved} 条")
                return saved
            return 0
        except Exception as e:
            logger.error(f"❌ [港股/AKShare] 行情预热失败: {symbol} - {e}")
            return 0
