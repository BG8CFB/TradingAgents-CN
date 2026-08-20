"""
预注入数据源加载器

从 DATASOURCE_REGISTRY 加载所有数据源，包装为轻量 ToolInfo。
本注册面仅供工具管理/可用性查询使用；预注入执行在
orchestrator/agents.build_tool_data。
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from app.engine.tools.datasources.registry import (
    DATASOURCE_REGISTRY,
    DatasourceSpec,
    resolve_real_fn,
)

logger = logging.getLogger(__name__)


@dataclass
class ToolInfo:
    """轻量工具描述对象（供注册中心/路由管理面使用）"""

    name: str
    description: str
    func: Callable
    metadata: Dict[str, Any] = field(default_factory=dict)


def load_datasource_tools(toolkit_config: Optional[Dict] = None) -> List[ToolInfo]:
    """
    加载所有预注入数据源工具

    从 DATASOURCE_REGISTRY 遍历，包装为 ToolInfo。
    可用性过滤在分析侧完成（基于 AvailabilityCache）。

    Args:
        toolkit_config: 工具配置字典（当前未使用，保留接口）

    Returns:
        ToolInfo 列表
    """
    all_tools = []

    for spec in DATASOURCE_REGISTRY:
        try:
            # lazy wrapper → 真实函数对象（经 _lazy_module/_lazy_func_name 元信息解析）
            real_fn = resolve_real_fn(spec.fn)

            tool = ToolInfo(
                name=spec.tool_id,
                description=spec.description,
                func=real_fn,
                metadata={
                    "tool_category": "builtin",
                    "tool_id": spec.tool_id,
                    "builtin_domains": spec.domains,
                },
            )
            all_tools.append(tool)

        except Exception as e:  # noqa: BLE001 - 单工具失败不阻断整体加载
            logger.error(f"❌ 包装工具 {spec.tool_id} 失败: {e}")

    logger.info(f"✅ 预注入数据源加载完成: {len(all_tools)} 个")
    return all_tools


def get_datasource_tool_specs() -> List[DatasourceSpec]:
    """获取所有数据源工具的规格"""
    return list(DATASOURCE_REGISTRY)
