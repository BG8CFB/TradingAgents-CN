"""
统一工具注册中心（管理面）

聚合内置数据源工具（builtin/）与 skill 脚本入口的元数据，
供工具管理路由（routers/tools.py）做清单展示与可用性查询。
引擎运行时的工具装配在 orchestrator/agents（预注入 + callable_tools），
MCP 运行时在 app/llm/mcp，均不经本注册中心。
"""

import logging
import threading
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 工具类型枚举（三类，供路由分类展示）
TOOL_TYPE_BUILTIN = "builtin"  # 项目内置工具（预注入数据源 + 可调用 builtin）
TOOL_TYPE_MCP = "mcp"  # 外部 MCP 连接器工具
TOOL_TYPE_SKILL = "skill"  # Skill 渐进式披露工具


class ToolRegistry:
    """
    统一工具注册中心 — 管理内置数据源与 skill 入口

    使用方式：
        registry = ToolRegistry.get_instance()
        metas = registry.get_builtin_tool_metas()
    """

    def __init__(self):
        # 内置工具（预注入数据源 + 可调用 skill 入口）
        self._builtin_tools: List = []
        self._builtin_metas: Dict[str, Dict] = {}

        # 是否已初始化
        self._initialized = False

    @classmethod
    def get_instance(cls) -> "ToolRegistry":
        """获取全局单例"""
        global _registry
        if _registry is None:
            with _registry_lock:
                if _registry is None:
                    _registry = cls()
        return _registry

    @classmethod
    def reset_instance(cls):
        """重置全局单例（测试用）"""
        global _registry
        with _registry_lock:
            _registry = None

    def initialize(self, toolkit_config: Optional[Dict] = None):
        """
        加载所有工具源

        Args:
            toolkit_config: 工具配置字典
        """
        if self._initialized:
            logger.info("[ToolRegistry] 已初始化，跳过重复初始化")
            return

        # 0. 初始化 SkillRegistry 单例，注入依赖回调
        self._init_skill_registry()

        # 1. 加载内置工具
        self._load_builtin_tools(toolkit_config)

        # 2. 注册 Skill 脚本入口为 builtin 工具
        self._load_skill_entrypoints()

        self._initialized = True
        logger.info(f"[ToolRegistry] 初始化完成: 内置={len(self._builtin_tools)}")

    @property
    def is_initialized(self) -> bool:
        """是否已完成初始化"""
        return self._initialized

    def ensure_initialized(self, toolkit_config: Optional[Dict] = None) -> None:
        """如果尚未初始化，则执行初始化（幂等）。"""
        if not self._initialized:
            self.initialize(toolkit_config)

    def _init_skill_registry(self):
        """初始化 SkillRegistry 单例并注入依赖检查/安装回调"""
        try:
            from app.engine.tools.skill.registry import SkillRegistry
            from app.engine.tools.skill.availability import check_skill_dependencies_raw
            from app.engine.tools.skill.dependency_installer import (
                install_skill_dependencies_sync,
            )

            registry = SkillRegistry.get_instance()
            registry.set_dependency_callbacks(
                check_callback=check_skill_dependencies_raw,
                install_callback=install_skill_dependencies_sync,
            )
            logger.debug("[ToolRegistry] SkillRegistry 依赖回调已注入")
        except Exception as e:  # noqa: BLE001 - skill 子系统初始化失败不阻断工具清单
            logger.warning(f"[ToolRegistry] SkillRegistry 初始化失败（可忽略）: {e}")

    def _load_builtin_tools(self, toolkit_config: Optional[Dict] = None):
        """加载内置工具（预注入数据源 + 可调用 skill 入口）"""
        try:
            from app.engine.tools.builtin.registry import CALLABLE_TOOL_REGISTRY
            from app.engine.tools.datasources import load_datasource_tools
            from app.engine.tools.datasources.loader import ToolInfo
            from app.engine.tools.datasources.registry import DATASOURCE_REGISTRY

            self._builtin_tools = load_datasource_tools(toolkit_config)

            # 可调用的 skill 入口同样进工具清单（管理面展示）
            self._builtin_tools.extend(
                ToolInfo(
                    name=spec.tool_id,
                    description=spec.description,
                    func=spec.fn,
                    metadata={
                        "tool_category": "builtin",
                        "tool_id": spec.tool_id,
                        "builtin_domains": spec.domains,
                    },
                )
                for spec in CALLABLE_TOOL_REGISTRY
            )

            # 从 spec 构建 metas（数据源 + 可调用入口，兼容旧接口）
            self._builtin_metas = {}
            for spec in [*DATASOURCE_REGISTRY, *CALLABLE_TOOL_REGISTRY]:
                self._builtin_metas[spec.tool_id] = {
                    "tool_id": spec.tool_id,
                    "display_name": spec.display_name,
                    "domains": spec.domains,
                    "markets": spec.markets,
                    "non_standard": spec.non_standard,
                }

            logger.info(f"[ToolRegistry] 内置工具加载完成: {len(self._builtin_tools)} 个")
        except Exception as e:  # noqa: BLE001
            logger.error(f"[ToolRegistry] 内置工具加载失败: {e}")
            self._builtin_tools = []
            self._builtin_metas = {}

    def _load_skill_entrypoints(self):
        """把 skill 的脚本入口注册为 builtin 工具"""
        try:
            from app.engine.tools.skill.entrypoint_loader import (
                load_all_skill_entrypoints,
            )

            result = load_all_skill_entrypoints()
            registered_count = sum(len(v) for v in result["registered"].values())
            if registered_count > 0:
                # 入口已注册进 builtin.registry（可调用注册表），
                # 重新执行一次加载把新增入口的 metas 拉进来
                self._load_builtin_tools()
                logger.info(f"[ToolRegistry] Skill 脚本入口已注册: {registered_count} 个")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[ToolRegistry] Skill 入口注册失败（可忽略）: {e}")

    def get_all_tools(self) -> List:
        """获取所有工具（内置数据源 + skill 入口）"""
        return list(self._builtin_tools)

    def get_builtin_tools(self) -> List:
        """获取所有内置工具（不过滤）"""
        return list(self._builtin_tools)

    def get_builtin_tool_metas(self) -> Dict[str, Dict]:
        """获取所有内置工具的元数据"""
        return dict(self._builtin_metas)


# 全局单例
_registry = None
_registry_lock = threading.Lock()


def get_all_tools(toolkit=None) -> List:
    """
    获取所有工具（routers/tools.py 入口）

    Args:
        toolkit: 工具配置（传递给内置工具加载器）

    Returns:
        工具列表
    """
    registry = ToolRegistry.get_instance()

    # 首次调用时自动初始化
    if not registry.is_initialized:
        toolkit_config = {}
        if toolkit:
            if isinstance(toolkit, dict):
                toolkit_config = toolkit
            elif hasattr(toolkit, "config"):
                toolkit_config = toolkit.config
        registry.initialize(toolkit_config)

    return registry.get_all_tools()
