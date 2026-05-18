"""
第一阶段智能体工厂

根据前端选择和配置文件，动态创建第一阶段智能体节点函数。
配置加载、查找、映射等工具方法统一委托给 DynamicAnalystFactory。
"""

from typing import Dict, Any, List, Callable

from app.engine.tools.registry import get_all_tools, ToolRegistry
from app.utils.logging_init import get_logger

logger = get_logger("simple_agent_factory")


class SimpleAgentFactory:
    """
    简单智能体工厂

    仅负责创建第一阶段智能体节点函数。
    配置加载、查找、进度映射等工具方法委托给 DynamicAnalystFactory。
    """

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
            max_tool_calls: 最大工具调用次数（默认12，由 config 控制）

        Returns:
            {internal_key: node_function}
        """
        from app.engine.agents.analysts.dynamic_analyst import DynamicAnalystFactory

        node_functions = {}
        seen_internal_keys = set()

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

            enable_mcp, mcp_loader = DynamicAnalystFactory._mcp_settings_from_toolkit(toolkit)
            tools = get_all_tools(
                toolkit=toolkit,
                enable_mcp=enable_mcp,
                mcp_tool_loader=mcp_loader
            )

            allowed_tool_names = agent_config.get("tools") or []
            if allowed_tool_names:
                allowed_set = {str(name).strip() for name in allowed_tool_names if str(name).strip()}
                filtered_tools = [
                    tool for tool in tools
                    if getattr(tool, "name", None) in allowed_set
                ]
                if filtered_tools:
                    tools = filtered_tools
                    logger.info(f"🔧 [工厂] 工具已按配置裁剪: {len(tools)}/{len(allowed_set)} 个匹配")
                else:
                    logger.warning(
                        f"⚠️ [工厂] 智能体 {name} 的工具白名单配置无效！"
                        f"配置的工具 {allowed_set} 均未找到，回退到全量工具。"
                        f"请检查配置文件中的 tools 字段是否正确。"
                    )

            tools = [DynamicAnalystFactory._wrap_tool_safe(tool, toolkit) for tool in tools]

            from app.engine.agents.analysts.simple_agent_template import create_simple_agent

            inject_tools_list = []
            if allowed_tool_names:
                registry = ToolRegistry.get_instance()
                if not registry._initialized:
                    registry.initialize()
                allowed_set = {str(name).strip() for name in allowed_tool_names if str(name).strip()}
                for bt in registry.get_builtin_tools():
                    bt_name = getattr(bt, "name", None)
                    if bt_name in allowed_set:
                        inject_tools_list.append(bt)
                if inject_tools_list:
                    logger.info(f"💉 [工厂] {name}: 准备注入 {len(inject_tools_list)} 个内置工具数据")

            node_function = create_simple_agent(
                name=name,
                slug=slug,
                llm=llm,
                tools=tools,
                system_prompt=system_prompt,
                max_tool_calls=max_tool_calls,
                inject_tools=inject_tools_list if inject_tools_list else None,
            )

            node_functions[internal_key] = node_function

        logger.info(f"✅ [工厂] 共创建 {len(node_functions)} 个智能体节点")
        return node_functions
