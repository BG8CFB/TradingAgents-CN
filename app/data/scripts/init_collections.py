"""
MongoDB 集合初始化脚本

创建 11 个业务集合 + 索引。
可重复执行（已存在的集合和索引会跳过）。

用法:
    python -m app.data.scripts.init_collections
"""

import asyncio
import logging

from app.data.storage.mongo.index_definitions import INDEX_DEFINITIONS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# 索引定义唯一事实源：app/data/storage/mongo/index_definitions.py
# 主键语义：业务域唯一键一律不含 data_source（单版本覆盖），详见该模块 docstring


async def init_collections(market: str = "CN") -> None:
    """创建指定市场的全部集合和索引"""
    from app.data.storage.mongo.collections import get_all_collections
    from app.data.storage.mongo.index_definitions import get_legacy_index_names

    try:
        from app.core.database import get_mongo_db
        db = get_mongo_db()
    except Exception as e:
        logger.error("无法连接 MongoDB: %s", e)
        return

    collection_map = get_all_collections(market)
    legacy_index_names = get_legacy_index_names()
    logger.info("开始初始化 %s 市场 %d 个集合", market, len(collection_map))

    for data_type, collection_name in collection_map.items():
        collection = db[collection_name]

        # 清理废弃的含 data_source 唯一索引（与新的单版本覆盖语义冲突）
        for idx_name in legacy_index_names.get(data_type, []):
            try:
                await collection.drop_index(idx_name)
                logger.info("  已删除废弃索引 %s.%s", collection_name, idx_name)
            except Exception:
                pass  # 索引不存在时跳过

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
