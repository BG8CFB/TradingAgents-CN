"""
第一阶段智能体工厂

根据前端选择和配置文件，动态创建第一阶段智能体节点函数。
配置加载、查找、映射等工具方法统一委托给 DynamicAnalystFactory。
"""

from typing import Dict, Any, List, Callable

from app.engine.tools.registry import get_all_tools, ToolRegistry
from app.engine.tools.builtin.registry import (
    get_specs_by_ids,
)
from app.engine.tools.builtin.domain_checker import AvailabilityCache
from app.utils.logging_init import get_logger

logger = get_logger("simple_agent_factory")


class SimpleAgentFactory:
    """简单智能体工厂"""

    @staticmethod
    def create_analysts(
        selected_analysts: List[str],
        llm: Any,
        toolkit: Any,
        max_tool_calls: int = 12
    ) -> Dict[str, Callable]:
        """
        创建第一阶段智能体节点函数

        Args:
            selected_analysts: 前端选择的分析师列表（slug 或 name）
            llm: LLM 实例
            toolkit: 工具配置
            max_tool_calls: 最大工具调用次数

        Returns:
            {internal_key: node_function}
        """
        from app.engine.agents.analysts.dynamic_analyst import DynamicAnalystFactory

        node_functions = {}
        seen_internal_keys = set()

        # 获取可用性缓存
        cache = AvailabilityCache.get_instance()

        for input_key in selected_analysts:
            agent_config = DynamicAnalystFactory.get_agent_config(input_key)
            if not agent_config:
                logger.warning(f"⚠️ 未找到智能体配置: {input_key}")
                continue

            slug = agent_config.get("slug", "")
            name = agent_config.get("name", "")
            system_prompt = agent_config.get("roleDefinition", "")

            internal_key = slug.replace("-analyst", "").replace("-", "_")

            if internal_key in seen_internal_keys:
                logger.warning(f"⚠️ 跳过重复的分析师: {input_key} -> {internal_key}")
                continue
            seen_internal_keys.add(internal_key)

            logger.info(f"🤖 [工厂] 创建智能体: {name} ({slug})")

            # ── 1. 解析分析师配置的工具列表（现在是 tool_id） ──

            config_tool_ids = agent_config.get("tools") or []

            # ── 2. 从配置中解析内置工具 ──

            config_specs = get_specs_by_ids(config_tool_ids)

            # 报告未在注册表中找到的 tool_id（可能是 MCP/Skill 工具）
            unknown_ids = set(config_tool_ids) - {s.tool_id for s in config_specs}
            if unknown_ids:
                logger.debug(f"🔄 [{name}] 非 builtin 工具ID: {unknown_ids}")

            # ── 3. 将所有内置工具包装为 LangChain Tool 用于预注入 ──
            # 不再按 AvailabilityCache 过滤：所有内置工具都尝试预注入，
            # 工具函数内部有回退机制处理无数据场景。
            # AvailabilityCache 仅用于标记"数据域是否有缓存"状态，
            # 传递给 _inject_tool_data 用于生成前缀说明。

            from langchain_core.tools import StructuredTool

            builtin_tools = []
            cache_unavailable_ids = []
            for spec in config_specs:
                try:
                    langchain_tool = StructuredTool.from_function(
                        func=spec.fn,
                        name=spec.tool_id,
                        description=spec.description,
                    )

                    existing_meta = getattr(langchain_tool, "metadata", None) or {}
                    try:
                        langchain_tool.metadata = {
                            **existing_meta,
                            "tool_category": "builtin",
                            "tool_id": spec.tool_id,
                        }
                    except Exception as e:
                        logger.debug(f"设置工具元数据失败: {e}")
                        pass

                    builtin_tools.append(langchain_tool)
                except Exception as e:
                    logger.error(f"❌ 包装内置工具 {spec.tool_id} 失败: {e}")

                # 记录缓存中标记为不可用的工具（仅用于显示，不阻止注入）
                if not cache.is_available(spec.tool_id):
                    cache_unavailable_ids.append(spec.tool_id)

            # ── 4. 获取可调用工具（MCP + Skill） ──

            enable_mcp, mcp_loader = DynamicAnalystFactory._mcp_settings_from_toolkit(toolkit)
            all_tools = get_all_tools(
                toolkit=toolkit,
                enable_mcp=enable_mcp,
                mcp_tool_loader=mcp_loader
            )

            registry = ToolRegistry.get_instance()
            if not registry._initialized:
                registry.initialize()

            # 只保留非内置工具（MCP + Skill 脚本入口）
            # 双重检查：metadata 标记 + tool_id 名称白名单，防止 metadata 设置失败时内置工具泄露到 bind_tools
            # 注意：skill 脚本入口（如 technical-screening.calc-indicators）虽然通过
            # BuiltinToolSpec 注册，但属于 LLM 可调用工具，不能被排除。
            from app.engine.tools.builtin.registry import is_skill_tool

            builtin_tool_ids = {spec.tool_id for spec in config_specs}
            callable_tools = []
            for t in all_tools:
                tool_name = getattr(t, "name", None)
                # skill 脚本入口工具：始终保留为可调用
                if tool_name and is_skill_tool(tool_name):
                    callable_tools.append(t)
                    continue
                # 检查1：metadata 标记
                if registry.is_builtin_tool(t):
                    continue
                # 检查2：名称在本次分析师配置的内置工具列表中
                if tool_name and tool_name in builtin_tool_ids:
                    logger.debug(
                        f"🔄 [工厂] 工具 '{tool_name}' metadata 未标记为 builtin 但匹配内置 tool_id，已排除"
                    )
                    continue
                # 检查3：ToolRegistry 的 _builtin_metas 中注册过的名称
                if tool_name and registry.is_builtin_tool_by_name(tool_name):
                    continue
                callable_tools.append(t)

            # 断路器包装
            callable_tools = [DynamicAnalystFactory._wrap_tool_safe(t, toolkit) for t in callable_tools]

            if builtin_tools:
                logger.info(
                    f"💉 [工厂] {name}: {len(builtin_tools)} 个内置工具将预注入"
                    f"{f' ({len(cache_unavailable_ids)} 个无缓存数据，仍尝试注入)' if cache_unavailable_ids else ''}, "
                    f"{len(callable_tools)} 个外部工具可调用"
                )

            from app.engine.agents.analysts.simple_agent_template import create_simple_agent

            node_function = create_simple_agent(
                name=name,
                slug=slug,
                llm=llm,
                tools=callable_tools,
                system_prompt=system_prompt,
                max_tool_calls=max_tool_calls,
                inject_tools=builtin_tools if builtin_tools else None,
                unavailable_tools=cache_unavailable_ids if cache_unavailable_ids else None,
            )

            node_functions[internal_key] = node_function

        logger.info(f"✅ [工厂] 共创建 {len(node_functions)} 个智能体节点")
        return node_functions
