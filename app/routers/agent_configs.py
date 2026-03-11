"""
按阶段读写智能体 YAML 配置 (phase1-4)
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
from pydantic import BaseModel, Field, validator

from app.routers.auth_db import get_current_user

# 导入动态分析师工厂，用于清除配置缓存
try:
    from app.engine.agents.analysts.dynamic_analyst import DynamicAnalystFactory
    DYNAMIC_ANALYST_AVAILABLE = True
except ImportError:
    DYNAMIC_ANALYST_AVAILABLE = False

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent-configs", tags=["agent-configs"])

import os


def _get_config_dir() -> Path:
    # 1. 优先从环境变量读取
    env_dir = os.getenv("AGENT_CONFIG_DIR")
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
# 可选文本字段（description / whenToUse / source）在现有配置中也可能较长，提升上限以兼容
MAX_DESC_LEN = 20000
MAX_GROUPS = 50
MAX_GROUP_LEN = 128
MAX_TOOLS = 200
MAX_TOOL_NAME_LEN = 128


class AgentMode(BaseModel):
    slug: str = Field(..., description="唯一标识", min_length=1)
    name: str = Field(..., description="显示名称", min_length=1)
    roleDefinition: str = Field(..., description="System Prompt", min_length=1)
    description: Optional[str] = Field(
        default=None, description="简要描述（默认使用 slug）"
    )
    whenToUse: Optional[str] = Field(default=None, description="可选的使用提示")
    groups: List[str] = Field(default_factory=list, description="可选权限分组")
    source: Optional[str] = Field(default=None, description="来源标记")
    tools: Optional[List[str]] = Field(
        default=None,
        description="允许使用的工具名称列表；为空或缺省表示全量可用",
    )
    initial_task: Optional[str] = Field(
        default=None,
        description="初始任务描述（1阶段专用，系统会自动拼接股票信息）",
    )

    @validator("slug", "name", "roleDefinition")
    def _not_blank(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("必填字段不能为空")
        return value.strip()

    @validator("slug", "name")
    def _limit_title_length(cls, value: str) -> str:
        if len(value) > MAX_TITLE_LEN:
            raise ValueError(f"字段长度超过限制（最多 {MAX_TITLE_LEN} 字符）")
        return value

    @validator("roleDefinition")
    def _limit_prompt_length(cls, value: str) -> str:
        if len(value) > MAX_TEXT_LEN:
            raise ValueError(f"roleDefinition 过长（最多 {MAX_TEXT_LEN} 字符）")
        return value

    @validator("description", "whenToUse", "source")
    def _limit_optional_fields(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        value = value.strip()
        if len(value) > MAX_DESC_LEN:
            raise ValueError(f"文本过长（最多 {MAX_DESC_LEN} 字符）")
        return value or None

    @validator("groups", each_item=True)
    def _validate_groups(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("分组名称不能为空")
        value = value.strip()
        if len(value) > MAX_GROUP_LEN:
            raise ValueError(f"分组名称过长（最多 {MAX_GROUP_LEN} 字符）")
        return value

    @validator("tools", each_item=True)
    def _validate_tools(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("工具名称不能为空")
        value = value.strip()
        if len(value) > MAX_TOOL_NAME_LEN:
            raise ValueError(f"工具名称过长（最多 {MAX_TOOL_NAME_LEN} 字符）")
        return value

    @validator("tools")
    def _limit_tools(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is None:
            return value
        unique = []
        seen = set()
        for item in value:
            if item in seen:
                continue
            seen.add(item)
            unique.append(item)
        if len(unique) > MAX_TOOLS:
            raise ValueError(f"工具数量超过限制（最多 {MAX_TOOLS} 个）")
        return unique


class AgentConfigPayload(BaseModel):
    customModes: List[AgentMode] = Field(default_factory=list, description="智能体列表")

    @validator("customModes")
    def _limit_modes_count(cls, value: List[AgentMode]) -> List[AgentMode]:
        if len(value) > MAX_MODES:
            raise ValueError(f"智能体数量过多（最多 {MAX_MODES} 个）")
        return value


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
        raise HTTPException(status_code=500, detail=f"读取配置失败: {exc}")

    return {
        "success": True,
        "data": {
            "phase": phase,
            "exists": True,
            "customModes": modes,
            "path": str(config_path),
        },
        "message": "ok",
    }


@router.put("/{phase}")
async def save_agent_config(
    payload: AgentConfigPayload,
    phase: int = FastAPIPath(..., ge=1, le=4, description="阶段编号：1-4"),
    user: dict = Depends(get_current_user),
):
    """
    保存/覆盖指定阶段的配置。
    - 校验 slug 唯一
    - 允许缺失文件，写入时自动创建
    """
    slugs = [mode.slug for mode in payload.customModes]
    if len(set(slugs)) != len(slugs):
        raise HTTPException(status_code=400, detail="slug 必须唯一")
    if len(payload.customModes) > MAX_MODES:
        raise HTTPException(status_code=400, detail=f"智能体数量超过限制（最多 {MAX_MODES} 个）")

    # 规范化：可选字段填充默认值
    normalized_modes: List[dict] = []
    for mode in payload.customModes:
        data = mode.model_dump(exclude_none=True)
        if "description" not in data or not data["description"]:
            data["description"] = mode.slug
        if "groups" not in data or data["groups"] is None:
            data["groups"] = []
        # tools 缺省或空表示全量工具；保留去重后的显式选择
        if "tools" in data:
            tools = data.get("tools") or []
            if tools:
                deduped_tools = []
                seen_tools = set()
                for tool_name in tools:
                    if tool_name in seen_tools:
                        continue
                    seen_tools.add(tool_name)
                    deduped_tools.append(tool_name)
                data["tools"] = deduped_tools
            else:
                data.pop("tools", None)
        normalized_modes.append(data)

    config_path = _config_path(phase)
    try:
        _dump_modes(config_path, normalized_modes)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"写入配置失败: {exc}")

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
