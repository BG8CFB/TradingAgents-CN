"""
Skill 系统数据模型

对应 MongoDB 集合：
- skill_state：记录每个 skill 的启停状态、已安装依赖、来源
- skill_install_logs：记录每次依赖安装的审计日志
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ConfigDict

from app.utils.timezone import now_tz
from .user import PyObjectId


# ──────────────────────────────────────────────────────────────────────
# Skill 包内 manifest.yaml 的 Pydantic 模型
# ──────────────────────────────────────────────────────────────────────


class SkillEntrypoint(BaseModel):
    """manifest.yaml 中声明的脚本入口（会被注册为 builtin 工具）"""

    name: str = Field(..., description="入口名（kebab-case），工具 ID 为 {skill_name}.{name}")
    display_name: str = Field(..., description="中文显示名")
    description: str = Field(..., description="工具描述，供 LLM 判断何时调用")
    module: str = Field(..., description="相对 skill 根目录的 Python 模块路径，如 scripts.entry")
    function: str = Field(..., description="模块内入口函数名")
    inject_args: Dict[str, Any] = Field(
        default_factory=dict,
        description="复用 BuiltinToolSpec.inject_args 机制",
    )
    markets: List[str] = Field(default_factory=lambda: ["CN", "HK", "US"], description="适用市场")
    domains: List[str] = Field(default_factory=list, description="依赖的数据域")
    allowed_tools: List[str] = Field(
        default_factory=list,
        alias="allowed-tools",
        description="该入口依赖的其他工具白名单",
    )

    model_config = ConfigDict(populate_by_name=True)


class SkillPythonDependency(BaseModel):
    """Python 包依赖"""

    package: str = Field(..., description="包名")
    version: str = Field(default="", description="版本约束（pip 风格，如 >=0.4.28）")
    hash: str = Field(default="", description="可选 sha256 哈希，防投毒")
    note: str = Field(default="", description="额外说明（如需要系统 C 库）")


class SkillEnvRequirement(BaseModel):
    """环境变量需求（不自动设置，仅提示）"""

    name: str = Field(..., description="变量名")
    required: bool = Field(default=True, description="是否必需")
    description: str = Field(default="", description="用途说明")


class SkillSource(BaseModel):
    """Skill 来源信息（用于审计与升级）"""

    type: str = Field(default="local", description="来源类型：local | git | registry")
    url: str = Field(default="", description="git URL 或 registry 地址")
    commit: str = Field(default="", description="git commit hash")
    installed_at: Optional[datetime] = Field(default=None, description="系统填写：安装时间")
    installed_by: str = Field(default="", description="系统填写：安装者")


class SkillManifest(BaseModel):
    """manifest.yaml 的 Pydantic 模型（解析 + 校验）"""

    schema_version: str = Field(default="1.0", description="manifest 自身版本")
    skill_name: str = Field(..., description="skill 名（必须与目录名一致，kebab-case）")
    entrypoints: List[SkillEntrypoint] = Field(
        default_factory=list,
        description="脚本入口列表",
    )
    python_dependencies: List[SkillPythonDependency] = Field(
        default_factory=list,
        description="Python 依赖",
    )
    system_dependencies: List[Dict[str, str]] = Field(
        default_factory=list,
        description="系统级依赖（仅描述，不自动安装）",
    )
    env: List[SkillEnvRequirement] = Field(
        default_factory=list,
        description="环境变量需求",
    )
    source: SkillSource = Field(default_factory=SkillSource, description="来源信息")

    model_config = ConfigDict(populate_by_name=True)


# ──────────────────────────────────────────────────────────────────────
# MongoDB 持久化模型
# ──────────────────────────────────────────────────────────────────────


class SkillState(BaseModel):
    """
    对应 MongoDB 集合 skill_state

    记录每个 skill 的启停状态、已安装依赖、来源、最后检查时间。
    启动时被 SkillRegistry 读取，避免重复安装依赖。
    """

    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    name: str = Field(..., description="skill 名（唯一键）")
    enabled: bool = Field(default=True, description="是否启用")
    installed_dependencies: List[str] = Field(
        default_factory=list,
        description="已成功安装的依赖包名列表",
    )
    source: SkillSource = Field(default_factory=SkillSource, description="来源")
    last_checked_at: Optional[datetime] = Field(default=None, description="最后一次依赖检查时间")
    last_installed_at: Optional[datetime] = Field(default=None, description="最后一次依赖安装时间")
    created_at: datetime = Field(default_factory=now_tz)
    updated_at: datetime = Field(default_factory=now_tz)

    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)


class SkillInstallLog(BaseModel):
    """
    对应 MongoDB 集合 skill_install_logs

    记录每次依赖安装的审计日志，用于追溯与合规。
    不记录完整 pip 输出（可能含敏感信息），仅记录摘要。
    """

    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    skill_name: str = Field(..., description="skill 名")
    source_url: str = Field(default="", description="来源 URL")
    source_commit: str = Field(default="", description="来源 commit")
    packages: List[Dict[str, str]] = Field(
        default_factory=list,
        description="本次安装的包列表，每项 {package, version, hash}",
    )
    status: str = Field(..., description="结果：success | failed | partial")
    error: str = Field(default="", description="失败时的错误摘要（不含完整输出）")
    duration_seconds: float = Field(default=0.0, description="安装耗时（秒）")
    installed_by: str = Field(default="system", description="触发者：system | user:{username}")
    installed_at: datetime = Field(default_factory=now_tz)

    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)


# ──────────────────────────────────────────────────────────────────────
# 对外 API 的响应模型
# ──────────────────────────────────────────────────────────────────────


class SkillDependencyStatus(BaseModel):
    """单个依赖的可用性状态"""

    package: str
    version_constraint: str = ""
    satisfied: bool
    installed_version: str = ""
    note: str = ""


class SkillAvailability(BaseModel):
    """Skill 整体可用性状态"""

    skill_name: str
    enabled: bool
    dependencies_satisfied: bool
    dependencies: List[SkillDependencyStatus] = Field(default_factory=list)
    env_satisfied: bool
    missing_env: List[str] = Field(default_factory=list)
    entrypoints_available: List[str] = Field(default_factory=list)
    entrypoints_unavailable: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class SkillSummary(BaseModel):
    """Skill 列表项摘要（用于管理界面卡片）"""

    name: str
    description: str
    version: str = "0.0.0"
    user_invocable: bool = True
    enabled: bool = True
    source_type: str = "local"
    has_scripts: bool = False
    has_manifest: bool = False
    entrypoint_count: int = 0
    dependencies_satisfied: bool = True
    dependencies_total: int = 0
    dependencies_missing: int = 0
