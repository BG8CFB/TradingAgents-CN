"""同步元数据链 source → data_source 存量迁移（组 7 命名迁移窗口 A）。

对 sync_checkpoints / sync_events / source_health 三个集合，把仅有 legacy
`source` 键的文档补写 `data_source = source`（不删 source 键，双键并存到
兼容窗口结束）。幂等可重跑：已有 data_source 的文档不再改动。

用法（宿主机 conda 环境，需 MongoDB 可达）：
    conda activate tradingagents
    python scripts/rename_metadata_source_field.py            # 执行迁移
    python scripts/rename_metadata_source_field.py --dry-run   # 只统计不写入
"""
import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# 宿主机维护脚本按开发语义运行：否则 .env 的 DEBUG=false 会触发生产环境
# ALLOWED_HOSTS 通配符校验直接拒绝导入（该校验针对 Web 服务，与迁移无关）
os.environ.setdefault("DEBUG", "true")

logger = logging.getLogger("scripts.rename_metadata_source_field")

# 迁移涉及的三个元数据集合（元数据集合无市场后缀）
COLLECTIONS = ("sync_checkpoints", "sync_events", "source_health")


async def rename_source_field(db, dry_run: bool = False) -> dict:
    """把三集合中仅有 source 键的文档补写 data_source=source。

    db 可传入任意 Motor/SimulatedMongoDB 风格对象（测试注入用）。
    返回 {集合名: 补写条数}；幂等：已迁移文档二次运行为 0。
    """
    stats: dict = {}
    for name in COLLECTIONS:
        coll = db[name]
        cursor = coll.find(
            {"source": {"$exists": True}, "data_source": {"$exists": False}},
            {"_id": 1, "source": 1},
        )
        updated = 0
        async for doc in cursor:
            if not dry_run:
                await coll.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"data_source": doc["source"]}},
                )
            updated += 1
        stats[name] = updated
        logger.info(
            "%s: %s %s 条文档补写 data_source%s",
            name, "需迁移" if dry_run else "已迁移", updated,
            "（干跑，未写入）" if dry_run else "",
        )
    return stats


async def main(dry_run: bool = False) -> int:
    from app.core.logging_config import setup_logging

    setup_logging("INFO")

    from app.core import database as db_module
    from app.core.database import init_database, get_mongo_db

    await init_database()
    try:
        db = get_mongo_db()
        stats = await rename_source_field(db, dry_run=dry_run)
        logger.info("迁移完成：%s", stats)
        return 0
    finally:
        await db_module.db_manager.close_connections()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="同步元数据 source→data_source 存量迁移")
    parser.add_argument("--dry-run", action="store_true", help="只统计待迁移条数，不写入")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(dry_run=args.dry_run)))
