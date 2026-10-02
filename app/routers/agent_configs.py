"""
按阶段读写智能体库（agent_specs 集合，DB 权威）

配置模型（2026-08 工具体系拆分后）：
- data_tools: 预注入数据源 id 列表（代码控制，启动时预取注入上下文）
- mcp_tools / skills: 可调用工具限制集合；缺省/空 = 默认全部可用
- default_selected: 发起分析时默认勾选（仅 phase1 有语义）
- 内置工具（calc）全员默认，不经配置

存储（2026-09 工作流通用化）：YAML 存放退役，读写走
app.engine.orchestrator.workflow.store（tombstone / builtin 语义在 store 层）。
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path as FastAPIPath
from pydantic import BaseModel, Field, field_validator

from app.routers.auth_db import get_current_user, require_admin
from app.core.response import safe_error_message
from app.engine.orchestrator.workflow import store

# 导入动态分析师工厂，用于清除配置缓存
try:
    from app.engine.agents.analysts.dynamic_analyst import DynamicAnalystFactory

    DYNAMIC_ANALYST_AVAILABLE = True
except ImportError:
    DYNAMIC_ANALYST_AVAILABLE = False

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent-configs", tags=["Agent Configs"])

MAX_MODES = 200
# 现有阶段配置中的提示词已远超 4k，为避免合法配置被拒绝，将上限提升
# 如需更严格控制，可改为从配置文件读取或按环境变量覆盖
MAX_TEXT_LEN = 20000
MAX_TITLE_LEN = 128
MAX_DESC_LEN = 20000
MAX_TOOLS = 200
MAX_TOOL_NAME_LEN = 128

# 迁移期已知的历史冗余键：保存时剥离，不落盘（引擎零消费）
LEGACY_MODE_KEYS = ("whenToUse", "groups", "source", "initial_task", "tools")


class AgentMode(BaseModel):
    slug: str = Field(..., description="唯一标识", min_length=1)
    name: str = Field(..., description="显示名称", min_length=1)
    roleDefinition: str = Field(..., description="System Prompt", min_length=1)
    description: Optional[str] = Field(default=None, description="简要描述（默认使用 slug）")
    data_tools: Optional[List[str]] = Field(
        default=None,
        description="预注入数据源 id 列表（缺省/空 = 不注入任何数据源）",
    )
    mcp_tools: Optional[List[str]] = Field(
        default=None,
        description="MCP 工具限制集合；缺省/空 = 默认全部可用",
    )
    skills: Optional[List[str]] = Field(
        default=None,
        description="Skill 入口限制集合；缺省/空 = 默认全部可用",
    )
    default_selected: Optional[bool] = Field(
        default=None,
        description="发起分析时默认勾选该智能体（仅 phase1 有语义；true/false 落盘，缺省 = 不勾选）",
    )

    @field_validator("slug", "name", "roleDefinition")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("必填字段不能为空")
        return v.strip()

    @field_validator("slug", "name")
    @classmethod
    def _limit_title_length(cls, v: str) -> str:
        if len(v) > MAX_TITLE_LEN:
            raise ValueError(f"字段长度超过限制（最多 {MAX_TITLE_LEN} 字符）")
        return v

    @field_validator("roleDefinition")
    @classmethod
    def _limit_prompt_length(cls, v: str) -> str:
        if len(v) > MAX_TEXT_LEN:
            raise ValueError(f"roleDefinition 过长（最多 {MAX_TEXT_LEN} 字符）")
        return v

    @field_validator("description")
    @classmethod
    def _limit_optional_fields(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if len(v) > MAX_DESC_LEN:
            raise ValueError(f"文本过长（最多 {MAX_DESC_LEN} 字符）")
        return v or None

    @field_validator("data_tools", "mcp_tools", "skills")
    @classmethod
    def _validate_tool_lists(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
        cleaned: List[str] = []
        seen: set = set()
        for item in v:
            if not isinstance(item, str) or not item.strip():
                continue  # 空白项（UI 残留）直接跳过
            item = item.strip()
            if len(item) > MAX_TOOL_NAME_LEN:
                raise ValueError(f"工具名称过长（最多 {MAX_TOOL_NAME_LEN} 字符）")
            if item in seen:
                continue
            seen.add(item)
            cleaned.append(item)
        if len(cleaned) > MAX_TOOLS:
            raise ValueError(f"工具数量超过限制（最多 {MAX_TOOLS} 个）")
        # 空列表与缺省语义相同（全部可用/不注入），统一存缺省
        return cleaned or None


class AgentConfigPayload(BaseModel):
    customModes: List[AgentMode] = Field(default_factory=list, description="智能体列表")

    @field_validator("customModes")
    @classmethod
    def _limit_modes_count(cls, v: List[AgentMode]) -> List[AgentMode]:
        if len(v) > MAX_MODES:
            raise ValueError(f"智能体数量过多（最多 {MAX_MODES} 个）")
        return v


def _storage_path_label(phase: int) -> str:
    """存储位置描述（UI 展示用；DB 时代无文件路径）"""
    return f"mongodb:agent_specs?phase={phase}"


@router.get("/{phase}")
async def get_agent_config(
    phase: int = FastAPIPath(..., ge=1, le=4, description="阶段编号：1-4"),
    user: dict = Depends(get_current_user),
):
    """
    读取指定阶段的智能体配置。
    阶段无条目且库未注入（如 phase4 无种子）时返回 exists=False，前端可提示。
    """
    try:
        modes = store.list_agent_specs(phase)
        injected = store.agent_collection_initialized()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=safe_error_message(exc, "读取配置失败"))

    exists = bool(modes) or injected

    # 迁移容错：剥离历史冗余键，旧 tools 归一化到 data_tools/skills
    normalized: List[dict] = []
    for mode in modes:
        if not isinstance(mode, dict):
            continue
        for key in LEGACY_MODE_KEYS:
            mode.pop(key, None)
        mode.setdefault("data_tools", [])
        normalized.append(mode)

    return {
        "success": True,
        "data": {
            "phase": phase,
            "exists": exists,
            "customModes": normalized,
            "path": _storage_path_label(phase),
        },
        "message": "ok" if exists else f"phase {phase} 无智能体配置",
    }


@router.put("/{phase}")
async def save_agent_config(
    payload: AgentConfigPayload,
    phase: int = FastAPIPath(..., ge=1, le=4, description="阶段编号：1-4"),
    user: dict = Depends(require_admin),
):
    """
    保存/覆盖指定阶段的配置（全量覆盖语义：不在 payload 的内置条目转 tombstone，
    用户条目物理删除——规则见 store.replace_phase_agent_specs）。
    - 校验 slug 唯一
    - data_tools 中未知 id 仅告警不阻断（数据源注册表可能尚未初始化）
    """
    slugs = [mode.slug for mode in payload.customModes]
    if len(set(slugs)) != len(slugs):
        raise HTTPException(status_code=400, detail="slug 必须唯一")
    if len(payload.customModes) > MAX_MODES:
        raise HTTPException(status_code=400, detail=f"智能体数量超过限制（最多 {MAX_MODES} 个）")

    # 已注册数据源 id 集合（用于未知 id 告警）
    try:
        from app.engine.tools.datasources.registry import DATASOURCE_REGISTRY

        known_datasource_ids = {s.tool_id for s in DATASOURCE_REGISTRY}
    except Exception:  # noqa: BLE001 - 注册表不可用时不阻断保存
        known_datasource_ids = set()

    normalized_modes: List[dict] = []
    for mode in payload.customModes:
        data = mode.model_dump(exclude_none=True)
        if not data.get("description"):
            data["description"] = mode.slug
        # model_dump 已剔除冗余键；此处再兜底剥离（防扩展/旧客户端字段）
        for key in LEGACY_MODE_KEYS:
            data.pop(key, None)
        data.setdefault("data_tools", [])
        unknown = [tid for tid in data["data_tools"] if tid not in known_datasource_ids]
        if unknown:
            logger.warning(f"⚠️ [agent-configs] 未知数据源 id（已保存但不会注入）: {unknown}")
        normalized_modes.append(data)

    try:
        store.replace_phase_agent_specs(phase, normalized_modes)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=safe_error_message(exc, "写入配置失败"))

    # 🔥 保存配置后清除智能体库与 AgentRegistry 的缓存
    # 这样新添加的智能体配置才能在分析任务中被正确加载（registry 含显示名/别名索引）
    if DYNAMIC_ANALYST_AVAILABLE:
        try:
            DynamicAnalystFactory.clear_cache()
            logger.info(f"✅ 已清除智能体配置缓存 (phase={phase})")
        except Exception as e:
            logger.warning(f"⚠️ 清除智能体配置缓存失败: {e}")
    try:
        from app.engine.orchestrator.registry import clear_registry_cache

        clear_registry_cache()
    except Exception as e:  # noqa: BLE001 - registry 缓存清理失败不影响配置保存
        logger.warning(f"⚠️ 清除 registry 缓存失败: {e}")

    return {
        "success": True,
        "data": {
            "phase": phase,
            "exists": True,
            "customModes": normalized_modes,
            "path": _storage_path_label(phase),
        },
        "message": "saved",
    }
