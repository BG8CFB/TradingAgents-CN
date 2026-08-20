"""
AI 可调用内置工具注册表

与 datasources/（预注入数据源，代码控制）相对：本注册面管理
LLM 在对话循环中主动调用的工具。目前静态内置工具为 calc
（不经本表，由 orchestrator 无条件挂载）；skill 脚本入口经
register_skill_entrypoint 在运行时动态注册/卸载。

设计对标 claude-code 的内置工具层：工具以 ToolDef 形态进入
runner 对话循环（app/llm/tools/wrappers.func_to_tooldef）。
"""

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class BuiltinToolSpec:
    """可调用工具规格声明"""

    tool_id: str
    display_name: str
    domains: List[str]
    markets: List[str]
    fn: Callable
    inject_args: Dict[str, Any]
    description: str
    non_standard: bool = False
    availability_check: Optional[str] = None


# 可调用工具注册表（skill 入口运行时追加；calc 不经本表）
CALLABLE_TOOL_REGISTRY: List[BuiltinToolSpec] = []

_TOOL_ID_INDEX: Dict[str, BuiltinToolSpec] = {s.tool_id: s for s in CALLABLE_TOOL_REGISTRY}


def register_skill_entrypoint(spec: BuiltinToolSpec) -> bool:
    """
    运行时追加注册 skill 脚本入口为可调用工具。

    由 SkillRegistry 发现 skill 的 entrypoints 后调用。
    同名 tool_id 重复注册会被拒绝（避免覆盖）。

    Args:
        spec: skill 脚本的 BuiltinToolSpec（tool_id 形如 {skill}.{entrypoint}）

    Returns:
        注册是否成功
    """
    if spec.tool_id in _TOOL_ID_INDEX:
        logger.warning(f"[BuiltinRegistry] tool_id 已存在，拒绝覆盖: {spec.tool_id}")
        return False
    CALLABLE_TOOL_REGISTRY.append(spec)
    _TOOL_ID_INDEX[spec.tool_id] = spec
    logger.info(f"[BuiltinRegistry] 已注册 skill 入口: {spec.tool_id}")
    return True


def unregister_skill_entrypoints(prefix: str) -> int:
    """
    按前缀（通常是 {skill_name}.）批量卸载 skill 工具。

    Args:
        prefix: skill_name 前缀（自动加 '.'）

    Returns:
        卸载的工具数量
    """
    full_prefix = prefix if prefix.endswith(".") else prefix + "."
    to_remove = [tid for tid in _TOOL_ID_INDEX if tid.startswith(full_prefix)]
    for tid in to_remove:
        spec = _TOOL_ID_INDEX.pop(tid)
        CALLABLE_TOOL_REGISTRY.remove(spec)
    if to_remove:
        logger.info(f"[BuiltinRegistry] 已卸载 {len(to_remove)} 个 skill 入口: {prefix}")
    return len(to_remove)


def is_skill_tool(tool_id: str) -> bool:
    """判断 tool_id 是否属于 skill 脚本入口（通过约定：含 '.' 分隔）"""
    return "." in tool_id and tool_id in _TOOL_ID_INDEX


def get_skill_entry_specs(tool_ids: List[str]) -> List[BuiltinToolSpec]:
    """按 tool_id 列表查找已注册的可调用入口，忽略不存在的"""
    return [_TOOL_ID_INDEX[tid] for tid in tool_ids if tid in _TOOL_ID_INDEX]


def get_all_callable_specs() -> List[BuiltinToolSpec]:
    """获取全部已注册的可调用工具规格"""
    return list(CALLABLE_TOOL_REGISTRY)
