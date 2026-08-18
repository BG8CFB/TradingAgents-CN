"""MongoDB 批量写入工具 — 分批执行 bulk_write 避免超时。"""

import logging
from typing import List

from pymongo import UpdateOne
from pymongo.results import BulkWriteResult

logger = logging.getLogger(__name__)

_BATCH_SIZE = 500


async def batched_bulk_write(collection, ops: List[UpdateOne], batch_size: int = _BATCH_SIZE) -> int:
    """分批执行 bulk_write，累计返回 upserted + modified 计数。

    H7 修复：中间批次失败时记录已成功计数并继续后续批次，而非直接上抛。
    这样调用方即使在部分批次失败时也能拿到已写入的数量，便于补偿重试。
    全部批次失败时上抛最后一个异常让调用方感知。
    """
    if not ops:
        return 0

    total_upserted = 0
    total_modified = 0
    total_batches = (len(ops) + batch_size - 1) // batch_size
    failed_batches = 0
    last_error: Exception | None = None

    for batch_idx, i in enumerate(range(0, len(ops), batch_size)):
        batch = ops[i : i + batch_size]
        try:
            result: BulkWriteResult = await collection.bulk_write(batch, ordered=False)
            total_upserted += result.upserted_count
            total_modified += result.modified_count
        except Exception as e:
            failed_batches += 1
            last_error = e
            logger.warning(
                "批量写入第 %d/%d 批失败 (本批 %d 条), 已成功 %d 条: %s",
                batch_idx + 1, total_batches, len(batch),
                total_upserted + total_modified, e,
            )

    if failed_batches > 0:
        logger.warning(
            "批量写入完成: %d/%d 批失败, %d/%d 条成功",
            failed_batches, total_batches, total_upserted + total_modified, len(ops),
        )
    elif len(ops) > batch_size:
        logger.debug(f"分批写入完成: {len(ops)} 条, {total_batches} 批")

    if failed_batches == total_batches and last_error:
        raise last_error

    return total_upserted + total_modified
