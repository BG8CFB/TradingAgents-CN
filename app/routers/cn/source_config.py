"""
数据源配置 API — 优先级持久化到 MongoDB
"""

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.response import ok, fail

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cn/data", tags=["CN Source Config"])


async def _load_priorities_from_db() -> Dict[str, List[str]]:
    """从 MongoDB 加载用户配置的优先级"""
    try:
        from app.core.database import get_database
        db = await get_database()
    except Exception:
        return {}

    try:
        cursor = db["system_configs"].find(
            {"config_type": "data_source_priority", "market": "CN"},
        )
        docs = await cursor.to_list(length=None)
        return {doc["domain"]: doc["sources"] for doc in docs if "domain" in doc and "sources" in doc}
    except Exception as e:
        logger.debug("加载优先级配置失败: %s", e)
        return {}


async def _save_priority_to_db(domain: str, sources: List[str]) -> bool:
    """将优先级配置保存到 MongoDB"""
    try:
        from app.core.database import get_database
        from app.utils.time_utils import now_utc
        db = await get_database()
    except Exception:
        return False

    try:
        await db["system_configs"].update_one(
            {"config_type": "data_source_priority", "market": "CN", "domain": domain},
            {
                "$set": {
                    "sources": sources,
                    "updated_at": now_utc().isoformat(),
                },
                "$setOnInsert": {
                    "config_type": "data_source_priority",
                    "market": "CN",
                    "domain": domain,
                },
            },
            upsert=True,
        )
        return True
    except Exception as e:
        logger.error("保存优先级配置失败: %s", e)
        return False


@router.get("/source-config")
async def get_source_config():
    """获取数据源配置（能力矩阵 + 用户自定义优先级）"""
    from app.data.processor.capability_registry import CapabilityRegistry, _DEFAULT_PRIORITY

    registry = CapabilityRegistry()
    matrix = registry.get_matrix_summary()

    # 从 MongoDB 加载用户配置的优先级
    db_priorities = await _load_priorities_from_db()

    # 合并：用户配置覆盖默认
    priorities = {}
    for domain in matrix:
        priorities[domain] = db_priorities.get(domain) or _DEFAULT_PRIORITY.get(domain, [])

    return ok(data={
        "capability_matrix": matrix,
        "priorities": priorities,
    })


class PriorityUpdateRequest(BaseModel):
    priority: list[str]


@router.put("/source-config/{domain}")
async def update_source_priority(domain: str, request: PriorityUpdateRequest):
    """更新指定域的数据源优先级（持久化到 MongoDB）"""
    from app.data.processor.capability_registry import CapabilityRegistry

    registry = CapabilityRegistry()

    # 校验域是否合法
    available = registry.get_available_sources(domain)
    if not available:
        return fail(message=f"不支持的数据域: {domain}")

    # 校验优先级中的源是否可用
    for source in request.priority:
        level = registry.get_support_level(domain, source)
        if level.value == "none":
            return fail(message=f"数据源 {source} 不支持域 {domain}")

    # 持久化到 MongoDB
    saved = await _save_priority_to_db(domain, request.priority)
    if not saved:
        # 降级：仅更新内存（单次请求有效）
        registry.set_user_priority(domain, request.priority)
        return ok(
            message=f"域 {domain} 优先级已更新（仅内存，持久化失败）",
            data={"domain": domain, "priority": request.priority},
        )

    # 同步更新 CapabilityRegistry 单例内存
    registry.set_user_priority(domain, request.priority)

    return ok(
        message=f"域 {domain} 数据源优先级已更新并持久化",
        data={"domain": domain, "priority": request.priority},
    )
