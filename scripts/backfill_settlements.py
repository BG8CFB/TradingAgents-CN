"""历史决策回填：扫描 analysis_reports 中已完成分析，登记结算记录并结算到期部分。

一次性脚本（P0）：让存量分析进入结算闭环——登记后由同一套结算逻辑定价/结算。
用法（宿主机 conda 环境，需 MongoDB 可达）：
    conda activate tradingagents
    python scripts/backfill_settlements.py                # 登记 + 结算到期记录
    python scripts/backfill_settlements.py --register-only  # 仅登记
    python scripts/backfill_settlements.py --realpha        # 存量 settled 记录补基准 alpha
    python scripts/backfill_settlements.py --reflect        # 存量 settled 记录生成教训（LLM，分批跑）
"""
import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# 宿主机维护脚本按开发语义运行：否则 .env 的 DEBUG=false 会触发生产环境
# ALLOWED_HOSTS 通配符校验直接拒绝导入（该校验针对 Web 服务，与回填无关）
os.environ.setdefault("DEBUG", "true")

logger = logging.getLogger("scripts.backfill_settlements")


async def main(register_only: bool = False, realpha: bool = False, reflect: bool = False) -> int:
    from app.core.logging_config import setup_logging

    setup_logging("INFO")

    from app.core import database as db_module
    from app.core.database import init_database, get_mongo_db
    from app.services.settlement_service import get_settlement_service

    await init_database()
    try:
        db = get_mongo_db()
        svc = get_settlement_service()

        if realpha:
            # 仅补基准字段（幂等）：不重新登记、不重定价股票腿
            updated = await svc.backfill_benchmarks()
            logger.info("基准回填完成：%s 条", updated)
            return 0

        if reflect:
            # 存量教训生成（每条一次 LLM 调用；万级存量为小时级长跑，建议分批：
            # 重复执行只处理未反思记录，reflection_retry_count>=3 自动跳过）
            stats = await svc.reflect_on_settlements(limit=10000)
            logger.info("反思回填完成：%s", stats)
            return 0

        projection = {
            "task_id": 1,
            "stock_symbol": 1,
            "stock_code": 1,
            "stock_name": 1,
            "market_type": 1,
            "analysis_date": 1,
            "structured_summary": 1,
            "decision": 1,
        }
        registered = skipped = 0
        async for doc in db.analysis_reports.find({"status": "completed"}, projection):
            if not doc.get("task_id"):
                continue
            result = {k: doc.get(k) for k in projection if k != "task_id"}
            task_id = await svc.register_from_result(doc["task_id"], "system", result)
            if task_id:
                registered += 1
            else:
                skipped += 1
        stats: dict = {}
        if not register_only:
            stats = await svc.settle_due(batch_size=10000)
        logger.info(
            "结算回填完成：登记 %s 条（跳过兜底/无信号 %s 条），结算 %s", registered, skipped, stats
        )
        return 0
    finally:
        await db_module.db_manager.close_connections()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="历史决策结算回填")
    parser.add_argument("--register-only", action="store_true", help="仅登记不结算")
    parser.add_argument(
        "--realpha", action="store_true", help="仅补存量 settled 记录的基准 alpha 字段（幂等）"
    )
    parser.add_argument(
        "--reflect", action="store_true", help="仅对存量 settled 记录生成教训写入交易记忆（LLM 调用，分批跑）"
    )
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(
            main(
                register_only=args.register_only,
                realpha=args.realpha,
                reflect=args.reflect,
            )
        )
    )
