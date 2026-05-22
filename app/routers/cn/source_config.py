"""
数据源配置 API — 优先级持久化到 MongoDB
"""

import logging
from typing import Dict, List

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.response import ok, fail

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cn/data", tags=["CN Source Config"])


async def _load_priorities_from_db() -> Dict[str, List[str]]:
    """从 MongoDB 加载用户配置的优先级（通过 DataInterface）"""
    from app.data.core.interface import DataInterface

    di = DataInterface.get_instance()

    domains = [
        "daily_quotes", "daily_indicators", "adj_factors",
        "financial_data", "basic_info", "news",
    ]

    priorities: Dict[str, List[str]] = {}
    for domain in domains:
        try:
            config = await di.get_config("CN", domain)
            if config and "sources" in config:
                priorities[domain] = config["sources"]
        except Exception as e:
            logger.debug("加载域 %s 优先级配置失败: %s", domain, e)

    return priorities


async def _save_priority_to_db(domain: str, sources: List[str]) -> bool:
    """将优先级配置保存到 MongoDB（通过 DataInterface）"""
    from app.data.core.interface import DataInterface

    di = DataInterface.get_instance()

    try:
        return await di.update_config("CN", domain, sources)
    except Exception as e:
        logger.error("保存优先级配置失败: %s", e)
        return False


@router.get("/source-config")
async def get_source_config():
    """获取数据源配置（能力矩阵 + 用户自定义优先级）"""
    from app.data.core.registry.capability import CapabilityRegistry
    from app.data.config import load_yaml
    _default_config = load_yaml("default_priorities.yaml")
    _DEFAULT_PRIORITY = _default_config.get("CN", {})

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
    from app.data.core.registry.capability import CapabilityRegistry

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
