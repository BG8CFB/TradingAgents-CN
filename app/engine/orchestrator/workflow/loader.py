"""默认工作流装配（spec 来源 = workflow_specs 集合，DB 权威 + 本地种子降级）。

- load_default_spec() → (WorkflowSpec, spec_hash)：执行侧统一入口
- 加载即校验（结构规则 + registry 锚点），DB 中被改坏的 spec 不进 executor
- 轻量模型缓存：spec_hash 未变的重复装配复用同一 WorkflowSpec 实例（frozen，共享安全）
"""

import logging
from typing import Dict, List, Tuple

from .spec import WorkflowSpec

logger = logging.getLogger("orchestrator.workflow.loader")

DEFAULT_WORKFLOW_SLUG = "default-4stage"

# spec_hash -> WorkflowSpec（frozen 模型，进程内共享安全；条目上限防御异常库）
_spec_cache: dict = {}
_SPEC_CACHE_MAX = 32


class WorkflowLoadError(Exception):
    """工作流加载失败（不存在/解析失败/schema 不符）——fail-fast，不静默回退"""


def load_workflow_by_slug(slug: str) -> Tuple[WorkflowSpec, str]:
    """按 slug 装配工作流 → (WorkflowSpec, spec_hash)。

    Raises:
        WorkflowLoadError: slug 不存在 / schema 校验失败 / 结构或锚点校验失败
    """
    from . import store, validator
    from .seeds import agent_spec_hash

    raw = store.get_workflow_spec(slug)
    if raw is None:
        raise WorkflowLoadError(f"工作流不存在: {slug}")

    spec_hash = agent_spec_hash(raw)
    cached = _spec_cache.get(spec_hash)
    if cached is not None:
        return cached, spec_hash

    try:
        spec = WorkflowSpec.model_validate(raw)
    except Exception as e:  # noqa: BLE001 - pydantic 校验失败统一转加载错误
        raise WorkflowLoadError(f"工作流 schema 校验失败: {slug} ({e})") from e

    try:
        validator.validate_or_raise(spec)
    except validator.WorkflowValidationError as e:
        raise WorkflowLoadError(f"工作流校验失败: {slug}, errors={e.errors}") from e

    if len(_spec_cache) >= _SPEC_CACHE_MAX:
        _spec_cache.clear()
    _spec_cache[spec_hash] = spec
    return spec, spec_hash


def load_default_spec() -> Tuple[WorkflowSpec, str]:
    """默认工作流 → (WorkflowSpec, spec_hash)"""
    return load_workflow_by_slug(default_workflow_slug())


def default_workflow_slug() -> str:
    """默认工作流 slug（system_configs 持久化，P5「设为默认」；未设置/不可达回落内置）"""
    from . import store

    slug = store.get_default_workflow_slug()
    return slug if slug else DEFAULT_WORKFLOW_SLUG


def check_required_inputs(spec: WorkflowSpec, plan) -> List[str]:
    """组装库契约与分析师报告键 → required_sources 编译期检查（纯数据装配 + 纯函数）。

    agent_specs 库不可达时跳过检查并降级告警（required 约束依赖库契约存在；
    种子降级路径下 list_agent_specs 仍返回种子条目，仅 DB 异常会走到这里）。
    pipeline 任务启动与 /api/workflows/validate-run 共用本入口。
    """
    from app.engine.orchestrator import registry
    from . import inputs as inputs_mod
    from . import store as workflow_store

    try:
        contracts = {entry["slug"]: entry.get("template_inputs", []) for entry in workflow_store.list_agent_specs()}
    except Exception as e:  # noqa: BLE001 - 库不可读不阻断任务，required 检查降级
        logger.warning(f"⚠️ [orchestrator] required 输入检查跳过（agent_specs 不可读）: {e}")
        return []
    # 键形态与 DynamicAnalystFactory.get_agent_config 的三种解析方式对齐
    # （slug / internal_key / 中文名），前端任一形态的选择都能命中报告键映射
    analyst_keys: Dict[str, Tuple[str, ...]] = {}
    for identity in registry._load_identities():
        if not identity.is_analyst:
            continue
        internal_key = identity.slug.replace("-analyst", "").replace("-", "_")
        report_keys = tuple(identity.report_keys)
        for lookup in (identity.slug, internal_key, identity.name):
            if lookup:
                analyst_keys[lookup] = report_keys
    return inputs_mod.check_required_sources(plan, spec, contracts, analyst_keys)


def clear_workflow_cache() -> None:
    """失效模型缓存（测试与配置热更新用；store 层文档缓存由 store 自身管理）"""
    _spec_cache.clear()
