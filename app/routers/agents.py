"""智能体库单条 CRUD（agent_specs 集合，设计文档 §7 API 表 agents 半区）。

与既有 /api/agent-configs（phase 全量覆盖视图，旧管理页）共存：本路由是
库级单条操作（新管理页 §5.4），写入同经 workflow.store 层。

「内置」判定 = slug 命中本地种子集（与文档 builtin 字段区分——后者是
seeder 的内容一致性标志，旧管理页允许编辑内置条目会把它翻成 false）：
- 内置条目：查看 + fork，PUT/DELETE 403（定制唯一路径 = fork 新 slug）
- 删除保护：被工作流 nodes 段引用的条目 409 + 引用列表（phase1 pool 动态
  分析师不构成结构性引用，删除仅影响默认勾选）
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path as FastAPIPath, Query
from pydantic import BaseModel, Field, field_validator

from app.core.response import safe_error_message
from app.engine.orchestrator import registry
from app.engine.orchestrator.workflow import store
from app.engine.orchestrator.workflow.seeds import agent_seed_by_slug
from app.routers.auth_db import get_current_user, require_admin
from app.routers.agent_configs import MAX_TEXT_LEN, MAX_TITLE_LEN

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["Agents"])


def _is_builtin(slug: str) -> bool:
    """内置判定：slug 命中本地种子集（新 API 口径，见模块 docstring）"""
    return slug in agent_seed_by_slug()


def _require_doc(slug: str) -> Dict[str, Any]:
    doc = store.get_agent_doc(slug)
    if doc is None or doc.get("deleted"):
        raise HTTPException(status_code=404, detail=f"智能体不存在: {slug}")
    return doc


def _require_editable(slug: str) -> Dict[str, Any]:
    doc = _require_doc(slug)
    if _is_builtin(slug):
        raise HTTPException(
            status_code=403,
            detail=f"内置智能体不可编辑/删除（fork 为私有副本后修改）: {slug}",
        )
    return doc


class AgentSpecPayload(BaseModel):
    """智能体条目（prompt/契约层；执行属性在 workflow spec 的 nodes 段）"""

    phase: int = Field(..., ge=1, le=4)
    slug: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    roleDefinition: str = Field(..., min_length=1)
    description: Optional[str] = None
    data_tools: Optional[List[str]] = None
    mcp_tools: Optional[List[str]] = None
    skills: Optional[List[str]] = None
    default_selected: Optional[bool] = None
    template_inputs: Optional[List[Dict[str, Any]]] = None

    @field_validator("slug", "name", "roleDefinition")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("必填字段不能为空")
        return v.strip()

    @field_validator("slug", "name")
    @classmethod
    def _limit_title(cls, v: str) -> str:
        if len(v) > MAX_TITLE_LEN:
            raise ValueError(f"字段长度超过限制（最多 {MAX_TITLE_LEN} 字符）")
        return v

    @field_validator("roleDefinition")
    @classmethod
    def _limit_prompt(cls, v: str) -> str:
        if len(v) > MAX_TEXT_LEN:
            raise ValueError(f"roleDefinition 过长（最多 {MAX_TEXT_LEN} 字符）")
        return v


class ForkPayload(BaseModel):
    new_slug: str = Field(..., min_length=1)
    name: Optional[str] = None


def _identity_extras(slug: str, phase: Any, spec: Dict[str, Any]) -> Dict[str, Any]:
    """节点身份补充（画布节点库/NodeSpec 派生用）。

    registry 命中 → 权威 kind/node_name/event_key/report_keys（与执行锚一致）；
    库外（自定义智能体）→ kind 按 phase 兜底（1→analyst，其余→debater，
    phase 无法区分 judge/trader，可在工作流节点卡改 type）、报告键为空
    （运行期不保证产出，不做假端口承诺）。
    """
    identity = registry.get_identity_by_slug(slug)
    if identity:
        return {
            "kind": identity.kind,
            "node_name": identity.node_name,
            "event_key": identity.event_key,
            "report_keys": list(identity.report_keys),
        }
    return {
        "kind": "analyst" if phase == 1 else "debater",
        "node_name": (spec or {}).get("name") or slug,
        "event_key": slug,
        "report_keys": [],
    }


@router.get("")
async def list_agents(
    phase: Optional[int] = Query(default=None, ge=1, le=4),
    user: dict = Depends(get_current_user),
):
    """智能体库列表（type 徽标由前端按 spec 字段推导；含引用计数）。"""
    try:
        docs = store.list_agent_docs(phase)
        # 引用计数一次聚合（工作流 nodes 段命中）
        refs: Dict[str, List[str]] = {}
        for wf in store.list_workflow_specs():
            for node in wf.get("nodes") or ():
                refs.setdefault((node or {}).get("slug"), []).append(wf.get("slug"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=safe_error_message(exc, "读取智能体库失败"))

    items = [
        {
            "slug": doc["_id"],
            "phase": doc.get("phase"),
            "position": doc.get("position"),
            "builtin": _is_builtin(doc["_id"]),
            "updated_at": doc.get("updated_at"),
            "spec": doc.get("spec") or {},
            "referenced_by": refs.get(doc["_id"], []),
            **_identity_extras(doc["_id"], doc.get("phase"), doc.get("spec") or {}),
        }
        for doc in docs
    ]
    return {"success": True, "data": {"agents": items}}


@router.post("")
async def create_agent(payload: AgentSpecPayload, user: dict = Depends(require_admin)):
    """新建智能体（与现存条目或内置 slug 冲突 409）。"""
    if _is_builtin(payload.slug):
        raise HTTPException(status_code=409, detail=f"slug 与内置智能体冲突: {payload.slug}")
    existing = store.get_agent_doc(payload.slug)
    if existing is not None and not existing.get("deleted"):
        raise HTTPException(status_code=409, detail=f"智能体 slug 已存在: {payload.slug}")

    spec = payload.model_dump(exclude={"phase"}, exclude_none=True)
    try:
        store.save_agent_spec(spec, payload.phase)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=safe_error_message(exc, "写入智能体失败"))
    logger.info(f"✅ [agents] 新建智能体: {payload.slug} (phase={payload.phase})")
    return {"success": True, "data": {"spec": spec}, "message": "created"}


@router.get("/{slug}")
async def get_agent(
    slug: str = FastAPIPath(..., min_length=1),
    user: dict = Depends(get_current_user),
):
    """智能体详情（spec + 元数据 + 引用列表）。"""
    doc = _require_doc(slug)
    return {
        "success": True,
        "data": {
            "spec": doc.get("spec") or {},
            "phase": doc.get("phase"),
            "position": doc.get("position"),
            "builtin": _is_builtin(slug),
            "updated_at": doc.get("updated_at"),
            "created_at": doc.get("created_at"),
            "referenced_by": store.agent_workflow_references(slug),
            **_identity_extras(slug, doc.get("phase"), doc.get("spec") or {}),
        },
    }


@router.put("/{slug}")
async def update_agent(
    payload: AgentSpecPayload,
    slug: str = FastAPIPath(..., min_length=1),
    user: dict = Depends(require_admin),
):
    """更新智能体（内置 403；phase/position 不可改）。"""
    doc = _require_editable(slug)
    if payload.slug != slug:
        raise HTTPException(status_code=400, detail=f"body.slug ({payload.slug}) 与路径 slug ({slug}) 不一致")
    if payload.phase != doc.get("phase"):
        raise HTTPException(status_code=400, detail="phase 不可修改（删除后在新 phase 重建）")

    spec = payload.model_dump(exclude={"phase"}, exclude_none=True)
    try:
        store.save_agent_spec(spec, doc["phase"], position=doc.get("position"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=safe_error_message(exc, "写入智能体失败"))
    logger.info(f"✅ [agents] 更新智能体: {slug}")
    return {"success": True, "data": {"spec": spec}, "message": "updated"}


@router.delete("/{slug}")
async def delete_agent(
    slug: str = FastAPIPath(..., min_length=1),
    user: dict = Depends(require_admin),
):
    """删除智能体（内置 403；被工作流引用 409 + 引用列表）。"""
    _require_editable(slug)
    referenced_by = store.agent_workflow_references(slug)
    if referenced_by:
        raise HTTPException(
            status_code=409,
            detail={"message": f"智能体被 {len(referenced_by)} 个工作流引用，不可删除", "referenced_by": referenced_by},
        )
    try:
        action = store.delete_agent_spec(slug)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=safe_error_message(exc, "删除智能体失败"))
    if action == "missing":
        raise HTTPException(status_code=404, detail=f"智能体不存在: {slug}")
    logger.info(f"🗑️ [agents] 删除智能体: {slug} ({action})")
    return {"success": True, "data": {"slug": slug, "action": action}, "message": "deleted"}


@router.post("/{slug}/fork")
async def fork_agent(
    payload: ForkPayload,
    slug: str = FastAPIPath(..., min_length=1),
    user: dict = Depends(require_admin),
):
    """复制为私有副本（新 slug；内置定制的唯一路径）。

    只复制 agent_specs 条目（prompt/契约层）；工作流侧切换引用（NodeRef.ref
    改指副本）由工作流编辑器在工作流 PUT 中完成。
    """
    doc = _require_doc(slug)
    if payload.new_slug == slug:
        raise HTTPException(status_code=400, detail="new_slug 不能与源 slug 相同")
    if _is_builtin(payload.new_slug):
        raise HTTPException(status_code=409, detail=f"new_slug 与内置智能体冲突: {payload.new_slug}")
    existing = store.get_agent_doc(payload.new_slug)
    if existing is not None and not existing.get("deleted"):
        raise HTTPException(status_code=409, detail=f"智能体 slug 已存在: {payload.new_slug}")

    spec = dict(doc.get("spec") or {})
    spec["slug"] = payload.new_slug
    spec["name"] = payload.name or f"{spec.get('name', slug)}（副本）"
    try:
        store.save_agent_spec(spec, doc.get("phase") or 1)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=safe_error_message(exc, "写入智能体副本失败"))
    logger.info(f"✅ [agents] fork: {slug} → {payload.new_slug}")
    return {"success": True, "data": {"spec": spec}, "message": "forked"}
