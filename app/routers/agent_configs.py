"""
按阶段读写智能体 YAML 配置 (phase1-3)

配置模型（2026-08 工具体系拆分后）：
- data_tools: 预注入数据源 id 列表（代码控制，启动时预取注入上下文）
- mcp_tools / skills: 可调用工具限制集合；缺省/空 = 默认全部可用
- 内置工具（calc）全员默认，不经配置
"""

import logging
from pathlib import Path
from typing import List, Optional

try:  # 可选文件锁，避免并发写损坏
    from filelock import FileLock
except Exception:  # pragma: no cover - 兼容未安装 filelock
    FileLock = None  # type: ignore
from contextlib import nullcontext

import yaml
from fastapi import APIRouter, Depends, HTTPException, Path as FastAPIPath
from pydantic import BaseModel, Field, field_validator

from app.routers.auth_db import get_current_user, require_admin
from app.core.response import safe_error_message

# 导入动态分析师工厂，用于清除配置缓存
try:
    from app.engine.agents.analysts.dynamic_analyst import DynamicAnalystFactory
    DYNAMIC_ANALYST_AVAILABLE = True
except ImportError:
    DYNAMIC_ANALYST_AVAILABLE = False

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent-configs", tags=["Agent Configs"])

from app.core.env import get_env  # noqa: E402 (intentional late import)


def _get_config_dir() -> Path:
    # 1. 优先从环境变量读取
    env_dir = get_env("AGENT_CONFIG_DIR")
    if env_dir:
        path = Path(env_dir)
        if path.exists():
            return path

    # 2. 默认使用项目根目录下的 config/agents (用户自定义配置)
    project_root = Path(__file__).resolve().parents[2]
    config_agents_dir = project_root / "config" / "agents"
    return config_agents_dir


CONFIG_DIR = _get_config_dir()
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
    description: Optional[str] = Field(
        default=None, description="简要描述（默认使用 slug）"
    )
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


def _config_path(phase: int) -> Path:
    return CONFIG_DIR / f"phase{phase}_agents_config.yaml"


def _load_modes(config_path: Path) -> List[dict]:
    with config_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    modes = data.get("customModes", []) or []
    if not isinstance(modes, list):
        raise ValueError("customModes 必须为列表")
    return modes


def _dump_modes(config_path: Path, modes: List[dict]) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = config_path.with_suffix(".tmp")
    payload = {"customModes": modes}
    lock_ctx = FileLock(str(config_path) + ".lock") if FileLock is not None else nullcontext()
    with lock_ctx:
        with tmp_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(
                payload,
                f,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            )
        tmp_path.replace(config_path)


@router.get("/{phase}")
async def get_agent_config(
    phase: int = FastAPIPath(..., ge=1, le=4, description="阶段编号：1-4"),
    user: dict = Depends(get_current_user),
):
    """
    读取指定阶段的智能体配置。
    文件不存在时返回 exists=False，前端可提示。
    """
    config_path = _config_path(phase)
    if not config_path.exists():
        return {
            "success": True,
            "data": {
                "phase": phase,
                "exists": False,
                "customModes": [],
                "path": str(config_path),
            },
            "message": f"{config_path.name} 不存在",
        }

    try:
        modes = _load_modes(config_path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=safe_error_message(exc, "读取配置失败"))

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
            "exists": True,
            "customModes": normalized,
            "path": str(config_path),
        },
        "message": "ok",
    }


@router.put("/{phase}")
async def save_agent_config(
    payload: AgentConfigPayload,
    phase: int = FastAPIPath(..., ge=1, le=4, description="阶段编号：1-4"),
    user: dict = Depends(require_admin),
):
    """
    保存/覆盖指定阶段的配置。
    - 校验 slug 唯一
    - 允许缺失文件，写入时自动创建
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

    config_path = _config_path(phase)
    try:
        _dump_modes(config_path, normalized_modes)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=safe_error_message(exc, "写入配置失败"))

    # 🔥 关键修复：保存配置后清除 DynamicAnalystFactory 的缓存
    # 这样新添加的智能体配置才能在分析任务中被正确加载
    if DYNAMIC_ANALYST_AVAILABLE:
        try:
            DynamicAnalystFactory.clear_cache()
            logger.info(f"✅ 已清除智能体配置缓存 (phase={phase})")
        except Exception as e:
            logger.warning(f"⚠️ 清除智能体配置缓存失败: {e}")

    return {
        "success": True,
        "data": {
            "phase": phase,
            "exists": True,
            "customModes": normalized_modes,
            "path": str(config_path),
        },
        "message": "saved",
    }
