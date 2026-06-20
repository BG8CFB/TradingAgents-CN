"""一次性迁移脚本：为历史业务数据补 data_source 字段。

背景：
    P1-3 修复后，业务集合的唯一索引和 upsert filter 均加入 data_source 维度，
    以支持多源数据共存。但历史数据可能缺少该字段，导致 upsert 时 filter
    匹配不到（data_source=None）而插入新文档而非更新。

    本脚本遍历 CN/HK/US 三市场的业务集合，对缺少 data_source 的文档
    补一个默认值 "unknown"，使后续 upsert 能正确匹配。

    迁移完成后建议运行 init_collections 重建索引（因唯一键已变更）。

用法:
    conda activate tradingagents
    python -m app.data.scripts.migrate_data_source

    # 或指定单市场
    python -m app.data.scripts.migrate_data_source --market CN
"""

import argparse
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# 需要迁移 data_source 的业务 domain（与 init_collections INDEX_DEFINITIONS 中
# 唯一索引含 data_source 的集合保持一致）
_DOMAINS_TO_MIGRATE = [
    "daily_quotes",
    "daily_indicators",
    "adj_factors",
    "corporate_actions",
    "financial_data",
    "connect_status",
    "southbound_holding",
    "pre_post_market",
    "intraday_quotes",
    "money_flow",
    "margin_trading",
    "dragon_tiger",
    "block_trade",
]

_DEFAULT_DATA_SOURCE = "unknown"


async def migrate_market(market: str, dry_run: bool = False) -> None:
    """为指定市场的业务集合补 data_source 字段。"""
    from app.core.database import get_mongo_db
    from app.data.storage.mongo.collections import get_collection_name

    db = get_mongo_db()

    for domain in _DOMAINS_TO_MIGRATE:
        coll_name = get_collection_name(domain, market)
        coll = db[coll_name]

        # 统计缺少 data_source 的文档数
        missing_count = await coll.count_documents({
            "$or": [
                {"data_source": {"$exists": False}},
                {"data_source": None},
                {"data_source": ""},
            ]
        })

        if missing_count == 0:
            logger.info("[%s/%s] 无需迁移，所有文档已含 data_source", market, domain)
            continue

        logger.info("[%s/%s] 发现 %d 条文档缺少 data_source", market, domain, missing_count)

        if dry_run:
            logger.info("[%s/%s] dry-run 模式，跳过实际更新", market, domain)
            continue

        # 批量补字段：用 $set 设置默认值
        result = await coll.update_many(
            {
                "$or": [
                    {"data_source": {"$exists": False}},
                    {"data_source": None},
                    {"data_source": ""},
                ]
            },
            {"$set": {"data_source": _DEFAULT_DATA_SOURCE}},
        )
        logger.info(
            "[%s/%s] 已更新 %d 条文档（matched=%d）",
            market, domain, result.modified_count, result.matched_count,
        )


async def main(market: str = None, dry_run: bool = False) -> None:
    markets = [market] if market else ["CN", "HK", "US"]
    logger.info("开始 data_source 迁移：markets=%s dry_run=%s", markets, dry_run)
    for m in markets:
        await migrate_market(m, dry_run=dry_run)
    logger.info("data_source 迁移完成")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="为历史业务数据补 data_source 字段")
    parser.add_argument("--market", choices=["CN", "HK", "US"], default=None, help="指定市场（默认全部）")
    parser.add_argument("--dry-run", action="store_true", help="只统计不实际更新")
    args = parser.parse_args()
    asyncio.run(main(market=args.market, dry_run=args.dry_run))
