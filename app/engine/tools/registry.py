"""
统一工具注册中心

管理三类工具：内置工具（Builtin）、外部 MCP 工具、Skill 工具。
提供统一的工具获取、按名称查询、可用性管理、类型分类接口。
"""
import asyncio
import logging
import threading
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# 工具类型枚举（三类）
TOOL_TYPE_BUILTIN = "builtin"       # 项目内置工具（含 LangGraph 工具 + MCP Provider 工具）
TOOL_TYPE_MCP = "mcp"              # 外部 MCP 连接器工具
TOOL_TYPE_SKILL = "skill"          # Skill 渐进式披露工具

# 全局单例
_registry = None
_registry_lock = threading.Lock()


class ToolRegistry:
    """
    统一工具注册中心 — 管理内置工具、外部 MCP、Skill

    使用方式：
        registry = ToolRegistry.get_instance()
        tools = registry.get_all_tools()
    """

    def __init__(self):
        # 四类工具缓存
        self._builtin_tools: List = []
        self._mcp_tools: List = []          # 外部 MCP 连接器工具
        self._skill_tools: List = []

        # 内置工具元数据（从 builtin/loader 获取）
        self._builtin_metas: Dict[str, Dict] = {}

        # 手动禁用的工具名称集合
        self._disabled_tools: set = set()

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

        # 1. 加载内置工具
        self._load_builtin_tools(toolkit_config)

        # 2. 尝试加载 Skill 的 load_skill Meta-Tool
        self._load_skill_meta_tool()

        self._initialized = True
        total = len(self._builtin_tools) + len(self._mcp_tools) + len(self._skill_tools)
        logger.info(
            f"[ToolRegistry] 初始化完成: "
            f"内置={len(self._builtin_tools)}, "
            f"MCP={len(self._mcp_tools)}, "
            f"Skill={len(self._skill_tools)}, "
            f"总计={total}"
        )

    def _load_builtin_tools(self, toolkit_config: Optional[Dict] = None):
        """加载内置工具"""
        try:
            from app.engine.tools.builtin import load_builtin_tools
            from app.engine.tools.builtin.loader import get_builtin_tool_specs
            from app.engine.tools.builtin.registry import BUILTIN_TOOL_REGISTRY

            self._builtin_tools = load_builtin_tools(toolkit_config)

            # 从 spec 构建 metas（兼容旧接口）
            self._builtin_metas = {}
            for spec in BUILTIN_TOOL_REGISTRY:
                self._builtin_metas[spec.tool_id] = {
                    "tool_id": spec.tool_id,
                    "display_name": spec.display_name,
                    "domains": spec.domains,
                    "markets": spec.markets,
                    "non_standard": spec.non_standard,
                }

            logger.info(f"[ToolRegistry] 内置工具加载完成: {len(self._builtin_tools)} 个")
        except Exception as e:
            logger.error(f"[ToolRegistry] 内置工具加载失败: {e}")
            self._builtin_tools = []
            self._builtin_metas = {}

    def _load_skill_meta_tool(self):
        """加载 Skill 的 load_skill Meta-Tool"""
        try:
            from app.engine.tools.skill import SkillRegistry

            # SkillRegistry.__init__ 内已自动调用 discover_skills()，无需重复调用
            skill_registry = SkillRegistry()

            from app.engine.tools.skill.meta_tool import create_load_skill_tool

            load_skill_tool = create_load_skill_tool(skill_registry)
            if load_skill_tool:
                self._skill_tools = [load_skill_tool]
                logger.info("[ToolRegistry] Skill Meta-Tool 加载完成")
        except Exception as e:
            logger.debug(f"[ToolRegistry] Skill Meta-Tool 加载失败（可忽略）: {e}")
            self._skill_tools = []

    def set_mcp_tools(self, tools: List):
        """
        设置 MCP 工具列表（由外部 MCP 连接管理器在连接建立后调用）

        Args:
            tools: 从外部 MCP 服务器加载的工具列表
        """
        self._mcp_tools = tools or []
        logger.info(f"[ToolRegistry] MCP 工具已更新: {len(self._mcp_tools)} 个")

    def get_all_tools(self) -> List:
        """
        获取所有可用工具（内置 + MCP + Skill），过滤已禁用的工具

        Returns:
            工具列表
        """
        all_tools = []

        # 内置工具（过滤禁用和不可用的）
        for tool in self._builtin_tools:
            name = getattr(tool, "name", None)
            if name and name not in self._disabled_tools:
                all_tools.append(tool)

        # MCP 工具
        for tool in self._mcp_tools:
            name = getattr(tool, "name", None)
            if name and name not in self._disabled_tools:
                all_tools.append(tool)

        # Skill 工具
        for tool in self._skill_tools:
            name = getattr(tool, "name", None)
            if name and name not in self._disabled_tools:
                all_tools.append(tool)

        return all_tools

    def get_tools_by_names(self, names: List[str]) -> List:
        """
        按名称获取工具，自动过滤禁用的

        Args:
            names: 工具名称列表

        Returns:
            匹配的工具列表
        """
        if not names:
            return self.get_all_tools()

        name_set = set(names)
        filtered = [
            tool for tool in self.get_all_tools()
            if getattr(tool, "name", None) in name_set
        ]

        return filtered

    def get_builtin_tools(self) -> List:
        """获取所有内置工具（不过滤）"""
        return list(self._builtin_tools)

    def get_builtin_tool_metas(self) -> Dict[str, Dict]:
        """获取所有内置工具的元数据"""
        return dict(self._builtin_metas)

    def get_mcp_provider_metas(self) -> List[Dict]:
        """获取本地 MCP Provider 工具元数据列表。

        MCP Provider 工具是项目内置的金融数据工具，通过 MCP 协议暴露，
        定义在 app/engine/mcp_provider/finance.py 中。
        """
        try:
            from app.routers.tools import _MCP_TOOLS
            return list(_MCP_TOOLS)
        except Exception:
            return []

    def get_tools_grouped_by_type(self) -> Dict[str, List]:
        """按类型分组返回工具名称和元数据（三类：builtin / mcp / skill）。

        Returns:
            {
                "builtin": [{"name": ..., "display_name": ..., ...}],
                "mcp": [{"name": ..., "source": ..., ...}],
                "skill": [{"name": ..., ...}],
            }
        """
        result = {
            TOOL_TYPE_BUILTIN: [],
            TOOL_TYPE_MCP: [],
            TOOL_TYPE_SKILL: [],
        }

        # 1. 内置工具（LangGraph 分析工具）
        for name, meta in self._builtin_metas.items():
            result[TOOL_TYPE_BUILTIN].append({
                "name": name,
                "display_name": meta.get("display_name", name),
                "description": "",
                **meta,
            })

        # 2. MCP Provider 工具也归入 builtin（项目自带，只是调用方式不同）
        result[TOOL_TYPE_BUILTIN].extend(self.get_mcp_provider_metas())

        # 3. 外部 MCP 工具
        for tool in self._mcp_tools:
            name = getattr(tool, "name", None)
            if name and name not in self._disabled_tools:
                meta = getattr(tool, "metadata", {}) or {}
                description = getattr(tool, "description", "") or ""
                source = meta.get("server_name", "mcp")
                result[TOOL_TYPE_MCP].append({
                    "name": name,
                    "description": description,
                    "source": source,
                })

        # 4. Skill 工具
        for tool in self._skill_tools:
            name = getattr(tool, "name", None)
            if name and name not in self._disabled_tools:
                description = getattr(tool, "description", "") or ""
                result[TOOL_TYPE_SKILL].append({
                    "name": name,
                    "description": description,
                })

        return result

    def classify_tool(self, tool_name: str) -> str:
        """根据工具名判断其类型（三类：builtin / mcp / skill）。

        Args:
            tool_name: 工具名称

        Returns:
            工具类型字符串: builtin | mcp | skill | unknown
        """
        # 1. 内置 LangGraph 工具
        if tool_name in self._builtin_metas:
            return TOOL_TYPE_BUILTIN

        # 2. MCP Provider 工具（也归为 builtin）
        try:
            from app.routers.tools import _MCP_TOOLS
            mcp_names = {t["name"] for t in _MCP_TOOLS}
            if tool_name in mcp_names:
                return TOOL_TYPE_BUILTIN
        except Exception:
            pass

        # 3. Skill 工具
        for tool in self._skill_tools:
            if getattr(tool, "name", None) == tool_name:
                return TOOL_TYPE_SKILL

        # 4. 外部 MCP 工具
        for tool in self._mcp_tools:
            if getattr(tool, "name", None) == tool_name:
                return TOOL_TYPE_MCP

        return "unknown"

    def get_tool_display_name(self, tool_name: str) -> str:
        """获取工具的中文显示名。优先用 builtin_metas，其次 MCP Provider。"""
        # 内置工具
        if tool_name in self._builtin_metas:
            return self._builtin_metas[tool_name].get("display_name", tool_name)

        # MCP Provider 工具
        try:
            from app.routers.tools import _MCP_TOOLS
            for t in _MCP_TOOLS:
                if t["name"] == tool_name:
                    return t.get("description", tool_name).split("（")[0].split("(")[0]
        except Exception:
            pass

        return tool_name

    @staticmethod
    def is_builtin_tool(tool) -> bool:
        """判断工具是否为内置工具"""
        meta = getattr(tool, "metadata", None) or {}
        return meta.get("tool_category") == "builtin"

    @staticmethod
    def is_builtin_tool_by_name(name: str) -> bool:
        """根据工具名判断是否为内置工具"""
        registry = ToolRegistry.get_instance()
        return name in registry._builtin_metas

    def toggle_tool(self, name: str, enabled: bool):
        """
        手动启用/禁用工具

        Args:
            name: 工具名称
            enabled: 是否启用
        """
        if enabled:
            self._disabled_tools.discard(name)
            logger.info(f"[ToolRegistry] 启用工具: {name}")
        else:
            self._disabled_tools.add(name)
            logger.info(f"[ToolRegistry] 禁用工具: {name}")

    def get_availability_summary(self) -> dict:
        """
        获取工具可用性摘要

        Returns:
            {
                "builtin": {"total": N, "available": N, "unavailable": N, ...},
                "mcp": {"total": N},
                "skill": {"total": N},
                "disabled": ["tool_name", ...]
            }
        """
        try:
            from app.engine.tools.builtin.domain_checker import AvailabilityCache

            cache = AvailabilityCache.get_instance()
            results = cache.all_results
            available = sum(1 for v in results.values() if v)
            builtin_summary = {
                "total": len(results),
                "available": available,
                "unavailable": len(results) - available,
                "market": cache.market,
            }
        except Exception as e:
            logger.warning(f"[ToolRegistry] 获取可用性摘要失败: {e}")
            builtin_summary = {}

        return {
            "builtin": builtin_summary,
            "mcp": {"total": len(self._mcp_tools)},
            "skill": {"total": len(self._skill_tools)},
            "disabled": sorted(self._disabled_tools),
        }


# ========================================================================
# 向后兼容的入口函数（供 simple_agent_factory, tools.py 等调用）
# ========================================================================

def get_all_tools(
    toolkit=None,
    enable_mcp: bool = False,
    mcp_tool_loader: Optional[Callable] = None,
    **kwargs,
) -> List:
    """
    获取所有工具（向后兼容接口）

    此函数保留旧签名，内部委托给 ToolRegistry。

    Args:
        toolkit: 工具配置（传递给内置工具加载器）
        enable_mcp: 是否包含 MCP 工具
        mcp_tool_loader: MCP 工具加载器（Callable）
        **kwargs: 忽略的其他参数（向后兼容）

    Returns:
        工具列表
    """
    registry = ToolRegistry.get_instance()

    # 首次调用时自动初始化
    if not registry._initialized:
        # 将 toolkit 转为字典格式
        toolkit_config = {}
        if toolkit:
            if isinstance(toolkit, dict):
                toolkit_config = toolkit
            elif hasattr(toolkit, 'config'):
                toolkit_config = toolkit.config
        registry.initialize(toolkit_config)

    # 如果需要 MCP 工具
    if enable_mcp and mcp_tool_loader:
        try:
            mcp_tools = list(mcp_tool_loader())
            # 过滤已禁用的
            mcp_tools = [
                t for t in mcp_tools
                if getattr(t, "name", None) not in registry._disabled_tools
            ]
            registry.set_mcp_tools(mcp_tools)
        except Exception as e:
            logger.warning(f"[ToolRegistry] MCP 工具加载失败: {e}")

    return registry.get_all_tools()
