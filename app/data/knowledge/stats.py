"""知识库引用校验计数（记分卡「引用有效率」的数据源）。

引擎侧在分析师报告落板后写入：当次注入 top-K 数、被引用序号、
无效引用剔除数。P0 结算记分卡按自己的口径从这里取数聚合。
同步 pymongo：写入口在分析工作线程，不走 motor。
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.data.storage.mongo.collections import get_collection_name

logger = logging.getLogger(__name__)


def _get_db():
    # 延迟导入：app.core.database 模块级导入会触发启动期配置校验
    from app.core.database import get_mongo_db_sync

    return get_mongo_db_sync()


def record_citation_stats(doc: Dict) -> bool:
    """写入一条引用校验记录（失败只记日志——计数不影响分析主链路）。"""
    try:
        db = _get_db()
        coll = db[get_collection_name("kb_citation_stats", "CN")]
        doc.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        coll.insert_one(doc)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[kb] 引用计数落库失败: {e}")
        return False


def query_citation_stats(
    task_id: Optional[str] = None,
    agent_key: Optional[str] = None,
    limit: int = 100,
) -> List[Dict]:
    """查询引用校验记录（最新在前，供记分卡与知识库页核查）。"""
    try:
        db = _get_db()
        coll = db[get_collection_name("kb_citation_stats", "CN")]
        query: Dict = {}
        if task_id:
            query["task_id"] = task_id
        if agent_key:
            query["agent_key"] = agent_key
        cursor = (
            coll.find(query, {"_id": 0})
            .sort("created_at", -1)
            .limit(max(1, min(limit, 1000)))
        )
        return list(cursor)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[kb] 引用计数查询失败: {e}")
        return []
