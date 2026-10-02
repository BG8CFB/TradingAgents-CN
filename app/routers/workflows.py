"""工作流 CRUD（workflow_specs 集合，设计文档 §7 API 表 + §5.4 管理页操作）。

- 内置工作流只读：PUT/DELETE 403（定制路径 = 复制出自定义副本后编辑）
- 自定义工作流删除 = 软删除（tombstone），历史任务 workflow_snapshot 回放不受影响
- validate：编辑器保存前校验（schema + 结构规则，错误定位字段路径，恒 200）
- validate-run：分析页裁剪的轻量编译校验（selected_nodes/stage_overrides 可行性）
- 设为默认：system_configs.system_settings.default_workflow_slug（任务创建缺省工作流）
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path as FastAPIPath
from pydantic import BaseModel, Field, ValidationError

from app.core.response import safe_error_message
from app.engine.orchestrator.workflow import store
from app.engine.orchestrator.workflow.loader import (
    WorkflowLoadError,
    check_required_inputs,
    default_workflow_slug,
)
from app.engine.orchestrator.workflow.spec import StageOverride, WorkflowSpec
from app.engine.orchestrator.workflow.validator import WorkflowValidationError, validate
from app.routers.auth_db import get_current_user, require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workflows", tags=["Workflows"])


def _parse_spec(payload: Dict[str, Any]) -> WorkflowSpec:
    """payload dict → WorkflowSpec（自定义工作流恒 builtin=false）。失败抛 400。"""
    try:
        spec = WorkflowSpec.model_validate(payload)
    except ValidationError as e:
        errors = ["{}: {}".format(".".join(str(p) for p in err["loc"]) or "<root>", err["msg"]) for err in e.errors()]
        raise HTTPException(status_code=400, detail={"errors": errors}) from e
    if spec.builtin:
        spec = spec.model_copy(update={"builtin": False})
    return spec


def _validate_or_400(spec: WorkflowSpec) -> None:
    """结构校验（自定义工作流不做 registry 锚点校验，见 validator.validate_or_raise）。"""
    errors = validate(spec)
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})


def _require_doc(slug: str) -> Dict[str, Any]:
    doc = store.get_workflow_doc(slug)
    if doc is None or doc.get("deleted"):
        raise HTTPException(status_code=404, detail=f"工作流不存在: {slug}")
    return doc


def _require_custom(slug: str) -> Dict[str, Any]:
    doc = _require_doc(slug)
    if doc.get("builtin"):
        raise HTTPException(
            status_code=403,
            detail=f"内置工作流不可修改/删除（复制为自定义副本后编辑）: {slug}",
        )
    return doc


class ValidateRunPayload(BaseModel):
    """分析页裁剪校验入参（CompileParams 的可序列化投影）"""

    workflow_slug: str = Field(..., min_length=1)
    selected_nodes: Optional[List[str]] = None
    stage_overrides: Dict[str, StageOverride] = Field(default_factory=dict)


def _stage_summary(spec: WorkflowSpec) -> List[Dict[str, Any]]:
    return [{"id": s.id, "mode": s.mode, "optional": bool(s.optional)} for s in spec.stages]


def _plan_summary(plan) -> Dict[str, Any]:
    """编译计划摘要（validate-run 返回；nodes = 实际会执行的节点 slug）"""
    stages = []
    for s in plan.stages:
        kind = type(s).__name__.replace("Planned", "").lower()
        if kind == "batch":
            nodes = list(s.slugs)
        elif kind == "debate":
            nodes = [n.slug for n in s.sides] + [s.judge.slug]
        else:
            nodes = [s.node.slug]
        stages.append({"stage_id": s.stage_id, "kind": kind, "nodes": nodes})
    return {"stages": stages, "total_units": plan.total_units()}


@router.get("")
async def list_workflows(user: dict = Depends(get_current_user)):
    """工作流列表（内置 + 自定义，带校验状态与默认标记）。"""
    try:
        docs = store.list_workflow_docs()
        # 未显式设置时回落内置默认（与任务创建的缺省解析同口径）
        default_slug = default_workflow_slug()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=safe_error_message(exc, "读取工作流列表失败"))

    items: List[Dict[str, Any]] = []
    for doc in docs:
        spec_raw = doc.get("spec") or {}
        errors: List[str] = []
        spec = None
        try:
            spec = WorkflowSpec.model_validate(spec_raw)
            errors = validate(spec)
        except ValidationError as e:  # noqa: PERF203 - 单条损坏不阻断列表
            errors = [f"schema: {e.errors()[0].get('msg', '校验失败')}"]
        except Exception:  # noqa: BLE001
            errors = ["校验执行失败"]
        items.append(
            {
                "slug": doc.get("_id"),
                "name": spec_raw.get("name") or doc.get("_id"),
                "description": spec_raw.get("description", ""),
                "enabled": spec_raw.get("enabled", True),
                "builtin": bool(doc.get("builtin")),
                "updated_at": doc.get("updated_at"),
                "stages": _stage_summary(spec) if spec is not None else [],
                "valid": not errors,
                "validation_errors": errors,
                "is_default": doc.get("_id") == default_slug,
            }
        )
    return {"success": True, "data": {"workflows": items, "default_slug": default_slug}}


@router.post("")
async def create_workflow(payload: Dict[str, Any], user: dict = Depends(require_admin)):
    """新建自定义工作流（slug 冲突 409；同名 tombstone 覆盖复活）。"""
    spec = _parse_spec(payload)
    _validate_or_400(spec)

    existing = store.get_workflow_doc(spec.slug)
    if existing is not None and not existing.get("deleted"):
        raise HTTPException(status_code=409, detail=f"工作流 slug 已存在: {spec.slug}")

    try:
        store.save_workflow_spec(spec.model_dump(mode="json"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=safe_error_message(exc, "写入工作流失败"))
    logger.info(f"✅ [workflows] 新建自定义工作流: {spec.slug}")
    return {"success": True, "data": {"workflow": spec.model_dump(mode="json")}, "message": "created"}


@router.get("/{slug}")
async def get_workflow(
    slug: str = FastAPIPath(..., min_length=1),
    user: dict = Depends(get_current_user),
):
    """工作流详情（完整 spec + 元数据）。"""
    doc = _require_doc(slug)
    return {
        "success": True,
        "data": {
            "workflow": doc.get("spec") or {},
            "builtin": bool(doc.get("builtin")),
            "updated_at": doc.get("updated_at"),
            "created_at": doc.get("created_at"),
        },
    }


@router.put("/{slug}")
async def update_workflow(
    payload: Dict[str, Any],
    slug: str = FastAPIPath(..., min_length=1),
    user: dict = Depends(require_admin),
):
    """更新自定义工作流（内置 403；body.slug 必须与路径一致）。"""
    _require_custom(slug)
    spec = _parse_spec(payload)
    if spec.slug != slug:
        raise HTTPException(status_code=400, detail=f"body.slug ({spec.slug}) 与路径 slug ({slug}) 不一致")
    _validate_or_400(spec)

    try:
        store.save_workflow_spec(spec.model_dump(mode="json"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=safe_error_message(exc, "写入工作流失败"))
    logger.info(f"✅ [workflows] 更新自定义工作流: {slug}")
    return {"success": True, "data": {"workflow": spec.model_dump(mode="json")}, "message": "updated"}


@router.delete("/{slug}")
async def delete_workflow(
    slug: str = FastAPIPath(..., min_length=1),
    user: dict = Depends(require_admin),
):
    """软删除自定义工作流（内置 403；删除当前默认时清默认设置回落内置）。"""
    _require_custom(slug)
    try:
        store.delete_workflow_spec(slug)
        if (store.get_default_workflow_slug() or "") == slug:
            store.clear_default_workflow_slug()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=safe_error_message(exc, "删除工作流失败"))
    logger.info(f"🗑️ [workflows] 软删除自定义工作流: {slug}")
    return {"success": True, "data": {"slug": slug}, "message": "deleted"}


@router.post("/{slug}/default")
async def set_default_workflow(
    slug: str = FastAPIPath(..., min_length=1),
    user: dict = Depends(require_admin),
):
    """设为默认工作流（workflow_slug 缺省的任务创建使用）。"""
    doc = _require_doc(slug)
    if not (doc.get("spec") or {}).get("enabled", True):
        raise HTTPException(status_code=400, detail=f"已停用的工作流不可设为默认: {slug}")
    try:
        store.set_default_workflow_slug(slug)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=safe_error_message(exc, "写入默认工作流失败"))
    return {"success": True, "data": {"default_slug": slug}, "message": "ok"}


@router.post("/validate")
async def validate_workflow(payload: Dict[str, Any], user: dict = Depends(require_admin)):
    """编辑器保存前校验：恒 200，错误列表定位字段/连线（不满足时前端禁用保存）。"""
    errors: List[str] = []
    try:
        spec = WorkflowSpec.model_validate(payload)
    except ValidationError as e:
        errors = ["{}: {}".format(".".join(str(p) for p in err["loc"]) or "<root>", err["msg"]) for err in e.errors()]
    else:
        errors = validate(spec)
    return {"success": True, "data": {"valid": not errors, "errors": errors}}


@router.post("/validate-run")
async def validate_run(payload: ValidateRunPayload, user: dict = Depends(get_current_user)):
    """分析页裁剪可行性校验：compile + required 槽检查，恒 200 由前端按 valid 判定。"""
    from app.engine.orchestrator.workflow.compiler import CompileError, compile_workflow
    from app.engine.orchestrator.workflow.loader import load_workflow_by_slug
    from app.engine.orchestrator.workflow.spec import CompileParams

    errors: List[str] = []
    plan = None
    try:
        spec, _ = load_workflow_by_slug(payload.workflow_slug)
        params = CompileParams(
            selected_nodes=tuple(payload.selected_nodes or ()),
            stage_overrides=dict(payload.stage_overrides),
        )
        plan = compile_workflow(spec, params)
        errors.extend(check_required_inputs(spec, plan))
    except (WorkflowLoadError, CompileError, WorkflowValidationError) as e:
        errors.append(str(e))

    data: Dict[str, Any] = {"valid": not errors, "errors": errors}
    if plan is not None:
        data["plan"] = _plan_summary(plan)
    return {"success": True, "data": data}
