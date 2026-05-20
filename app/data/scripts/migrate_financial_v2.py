"""
stock_financial_data 集合迁移脚本

为现有记录添加 statement_type 字段，重建唯一索引。

迁移内容：
  1. 为所有没有 statement_type 的记录设置 statement_type="indicator"
  2. 删除旧唯一索引（如果基于 symbol+report_period+data_source）
  3. 创建新唯一索引（基于 symbol+report_period+statement_type）

用法:
    python -m app.data.scripts.migrate_financial_v2
"""

import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def migrate_financial_data(collection_name: str = "stock_financial_data") -> dict:
    """
    执行财务数据集合迁移。

    Returns:
        {"matched": N, "modified": N}
    """
    try:
        from app.core.database import get_database
        db = await get_database()
    except Exception as e:
        logger.error("无法连接 MongoDB: %s", e)
        return {"matched": 0, "modified": 0, "error": str(e)}

    collection = db[collection_name]

    # 1. 为缺少 statement_type 的记录设置默认值
    result = await collection.update_many(
        {"statement_type": {"$exists": False}},
        {"$set": {"statement_type": "indicator"}},
    )
    logger.info(
        "集合 %s: %d 条记录需要更新, %d 条已修改",
        collection_name, result.matched_count, result.modified_count,
    )

    # 2. 检查并重建唯一索引
    existing_indexes = await collection.index_information()

    # 目标索引名
    target_index_key = [("symbol", 1), ("report_period", -1), ("statement_type", 1)]
    target_index_name = "symbol_1_report_period_-1_statement_type_1"

    if target_index_name not in existing_indexes:
        # 删除可能存在的旧唯一索引
        old_index_patterns = ["symbol_1_report_period_-1", "symbol_1_report_period_-1_data_source_1"]
        for old_name in old_index_patterns:
            if old_name in existing_indexes:
                try:
                    await collection.drop_index(old_name)
                    logger.info("已删除旧索引: %s", old_name)
                except Exception as e:
                    logger.warning("删除旧索引 %s 失败: %s", old_name, e)

        # 创建新唯一索引
        try:
            await collection.create_index(target_index_key, unique=True)
            logger.info("已创建新唯一索引: %s", target_index_name)
        except Exception as e:
            logger.error("创建唯一索引失败: %s", e)

    return {
        "matched": result.matched_count,
        "modified": result.modified_count,
    }


async def main():
    for collection_name in ("stock_financial_data", "stock_financial_data_hk", "stock_financial_data_us"):
        logger.info("迁移集合: %s", collection_name)
        result = await migrate_financial_data(collection_name)
        logger.info("结果: %s", result)


if __name__ == "__main__":
    asyncio.run(main())
