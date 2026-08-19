"""一次性迁移脚本：按「单版本覆盖」主键语义去重存量多源数据。

背景：旧唯一键含 data_source（多源并存），新语义（index_definitions.py）
要求同自然键只保留一份当前生效文档。本脚本在建新唯一索引**之前**运行：

    1. 对三市场每个业务域按新唯一键分组
    2. 每组保留「源优先级最高 → updated_at 最新」的一条，删除其余
    3. 打印删除统计并写入 sync_events 留痕（DEDUPE_MIGRATION 事件）

用法（conda tradingagents 环境，需 docker MongoDB 已启动）:
    python -m app.data.scripts.dedupe_for_single_version          # 干跑（只统计）
    python -m app.data.scripts.dedupe_for_single_version --apply  # 实际删除
"""

import asyncio
import logging
from datetime import datetime, timezone

from app.data.storage.mongo.collections import get_all_collections
from app.data.storage.mongo.index_definitions import INDEX_DEFINITIONS, get_unique_key

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# 源优先级（与 config/data 优先级默认一致）：数值越小越优先保留
_SOURCE_PRIORITY = {"tushare": 1, "akshare": 2, "baostock": 3}
_DEFAULT_PRIORITY = 9

# 排序键兜底：非时序域按 updated_at 取最新
_FALLBACK_SORT_FIELD = "updated_at"


def _sort_field(domain: str) -> str:
    """分组内保留排序字段：时序域按业务时间倒序，主表域按 updated_at 倒序。"""
    key_fields = get_unique_key(domain)
    for candidate in ("trade_date", "datetime", "ex_date", "report_period", "cal_date"):
        if candidate in key_fields:
            return candidate
    return _FALLBACK_SORT_FIELD


async def dedupe_market(db, market: str, apply: bool) -> int:
    """对单个市场执行去重，返回（若 apply）删除的文档总数。"""
    collection_map = get_all_collections(market)
    total_deleted = 0

    for domain, collection_name in collection_map.items():
        if domain not in INDEX_DEFINITIONS:
            continue
        try:
            key_fields = get_unique_key(domain)
        except KeyError:
            continue

        collection = db[collection_name]
        group_id = {f: f"${f}" for f in key_fields}

        pipeline = [
            {"$group": {
                "_id": group_id,
                "docs": {"$push": {"_id": "$_id",
                                   "data_source": "$data_source",
                                   _sort_field(domain): f"${_sort_field(domain)}"}},
                "count": {"$sum": 1},
            }},
            {"$match": {"count": {"$gt": 1}}},
        ]

        try:
            groups = await collection.aggregate(pipeline).to_list(None)
        except Exception as e:
            logger.warning(f"  {collection_name}: 分组查询失败，跳过: {e}")
            continue

        if not groups:
            continue

        deleted_for_collection = 0
        for group in groups:
            docs = sorted(
                group["docs"],
                key=lambda d: (
                    _SOURCE_PRIORITY.get(d.get("data_source") or "", _DEFAULT_PRIORITY),
                    str(d.get(_sort_field(domain)) or ""),
                ),
            )
            # 保留优先级最高的一条（排序后第一个），删除其余
            to_delete = [d["_id"] for d in docs[1:]]
            if not apply:
                logger.info(
                    f"  [干跑] {collection_name} 组 {group['_id']}: "
                    f"{group['count']} 条 -> 保留 1，将删除 {len(to_delete)}"
                )
                deleted_for_collection += len(to_delete)
                continue
            if to_delete:
                result = await collection.delete_many({"_id": {"$in": to_delete}})
                deleted_for_collection += result.deleted_count

        if deleted_for_collection:
            logger.info(
                f"  {collection_name}{'（干跑）' if not apply else ''}: 去重删除 "
                f"{deleted_for_collection} 条"
            )
            total_deleted += deleted_for_collection

    return total_deleted


async def record_event(db, market: str, deleted: int, apply: bool):
    """把迁移结果写入 sync_events 留痕（多源差异去向，符合单版本覆盖语义）。"""
    try:
        await db["sync_events"].insert_one({
            "market": market,
            "event_type": "DEDUPE_MIGRATION",
            "domain": "all",
            "source": "migration",
            "message": (
                f"单版本覆盖去重迁移{'（干跑）' if not apply else ''}: "
                f"删除 {deleted} 条多源重复文档"
            ),
            "created_at": datetime.now(timezone.utc),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        logger.warning(f"写迁移事件失败: {e}")


async def main(apply: bool = False):
    from app.core.database import get_mongo_db

    db = get_mongo_db()
    mode = "实际删除" if apply else "干跑（仅统计）"
    logger.info(f"=== 单版本覆盖去重迁移（{mode}） ===")

    grand_total = 0
    for market in ("CN", "HK", "US"):
        logger.info(f"--- {market} 市场 ---")
        deleted = await dedupe_market(db, market, apply)
        await record_event(db, market, deleted, apply)
        grand_total += deleted

    logger.info(f"=== 完成（{mode}）: 共处理重复文档 {grand_total} 条 ===")
    if not apply:
        logger.info("确认无误后执行: python -m app.data.scripts.dedupe_for_single_version --apply")


if __name__ == "__main__":
    import sys
    asyncio.run(main(apply="--apply" in sys.argv))
