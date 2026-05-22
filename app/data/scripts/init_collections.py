"""
MongoDB 集合初始化脚本

创建 11 个业务集合 + 索引。
可重复执行（已存在的集合和索引会跳过）。

用法:
    python -m app.data.scripts.init_collections
"""

import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# 索引定义: {集合类型 → [(索引字段列表, 是否唯一), ...]}
INDEX_DEFINITIONS = {
    "basic_info": [
        ([("symbol", 1)], True),
    ],
    "trade_calendar": [
        ([("exchange", 1), ("cal_date", 1)], True),
        ([("cal_date", 1)], False),
    ],
    "daily_quotes": [
        ([("symbol", 1), ("trade_date", -1), ("period", 1)], True),
        ([("trade_date", -1)], False),
    ],
    "daily_indicators": [
        ([("symbol", 1), ("trade_date", -1)], True),
        ([("trade_date", -1)], False),
    ],
    "adj_factors": [
        ([("symbol", 1), ("trade_date", -1)], True),
    ],
    "financial": [
        ([("symbol", 1), ("report_period", -1), ("statement_type", 1)], True),
        ([("report_period", -1)], False),
    ],
    "market_quotes": [
        ([("symbol", 1)], True),
    ],
    "news": [
        ([("content_hash", 1)], True),
        ([("symbol", 1), ("pub_date", -1)], False),
    ],
    "sync_checkpoints": [
        ([("domain", 1), ("source", 1)], True),
    ],
    "sync_events": [
        ([("event_type", 1), ("timestamp", -1)], False),
        ([("domain", 1), ("timestamp", -1)], False),
    ],
    "source_health": [
        ([("source", 1), ("domain", 1)], True),
    ],
}


async def init_collections(market: str = "CN") -> None:
    """创建指定市场的全部集合和索引"""
    from app.data.storage.mongo.collections import get_all_collections

    try:
        from app.core.database import get_database
        db = await get_database()
    except Exception as e:
        logger.error("无法连接 MongoDB: %s", e)
        return

    collection_map = get_all_collections(market)
    logger.info("开始初始化 %s 市场 %d 个集合", market, len(collection_map))

    for data_type, collection_name in collection_map.items():
        collection = db[collection_name]

        # 获取索引定义
        index_specs = INDEX_DEFINITIONS.get(data_type, [])

        for fields, unique in index_specs:
            index_name = "_".join(f"{k}_{v}" for k, v in fields)
            try:
                await collection.create_index(fields, unique=unique)
                logger.info("  索引 %s.%s 创建成功 (unique=%s)", collection_name, index_name, unique)
            except Exception as e:
                logger.warning("  索引 %s.%s 创建失败: %s", collection_name, index_name, e)

    logger.info("集合初始化完成")


async def main():
    for market in ("CN", "HK", "US"):
        await init_collections(market)


if __name__ == "__main__":
    asyncio.run(main())
