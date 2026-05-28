"""MongoDB 批量写入工具 — 分批执行 bulk_write 避免超时。"""

import logging
from typing import List

from pymongo import UpdateOne
from pymongo.results import BulkWriteResult

logger = logging.getLogger(__name__)

_BATCH_SIZE = 500


async def batched_bulk_write(collection, ops: List[UpdateOne], batch_size: int = _BATCH_SIZE) -> int:
    """分批执行 bulk_write，累计返回 upserted + modified 计数。"""
    if not ops:
        return 0

    total_upserted = 0
    total_modified = 0

    for i in range(0, len(ops), batch_size):
        batch = ops[i : i + batch_size]
        result: BulkWriteResult = await collection.bulk_write(batch, ordered=False)
        total_upserted += result.upserted_count
        total_modified += result.modified_count

    if len(ops) > batch_size:
        logger.debug(f"分批写入完成: {len(ops)} 条, {len(ops) // batch_size + 1} 批")

    return total_upserted + total_modified
