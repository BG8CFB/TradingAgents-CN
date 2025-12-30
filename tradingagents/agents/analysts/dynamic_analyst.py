
import os
import yaml
import logging
from typing import List, Dict, Any, Callable, Optional

from tradingagents.agents.utils.generic_agent import GenericAgent
from tradingagents.tools.registry import get_all_tools
from tradingagents.utils.logging_init import get_logger
from tradingagents.utils.tool_logging import log_analyst_module

logger = get_logger("analysts.dynamic")

class DynamicAnalystFactory:
    """
    动态分析师工厂
    根据配置文件动态生成智能体，不再需要为每个角色编写单独的 Python 文件。
    """
    
    _config_cache = {}
    _config_mtime = {}

    @classmethod
    def load_config(cls, config_path: str = None) -> Dict[str, Any]:
        """加载智能体配置文件"""
        if not config_path:
            # 1. 优先使用环境变量 AGENT_CONFIG_DIR
            env_dir = os.getenv("AGENT_CONFIG_DIR")
            if env_dir and os.path.exists(env_dir):
                config_path = os.path.join(env_dir, "phase1_agents_config.yaml")
            else:
                # 获取当前文件所在目录
                current_dir = os.path.dirname(os.path.abspath(__file__))
                # tradingagents/agents/analysts -> tradingagents/agents -> tradingagents -> root
                project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
                
                # 2. 尝试使用 config/agents/phase1_agents_config.yaml
                config_dir = os.path.join(project_root, "config", "agents")
                config_path_candidate = os.path.join(config_dir, "phase1_agents_config.yaml")
                
                if os.path.exists(config_path_candidate):
                    config_path = config_path_candidate
                else:
                    # 3. 回退到 tradingagents/agents/phase1_agents_config.yaml
                    agents_dir = os.path.dirname(current_dir)
                    config_path = os.path.join(agents_dir, "phase1_agents_config.yaml")

        try:
            mtime = os.path.getmtime(config_path)
        except Exception:
            mtime = None

        # 命中缓存且文件未变化则复用
        if (
            config_path in cls._config_cache
            and config_path in cls._config_mtime
            and mtime is not None
            and cls._config_mtime.get(config_path) == mtime
        ):
            return cls._config_cache[config_path]

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                cls._config_cache[config_path] = config or {}
                if mtime is not None:
                    cls._config_mtime[config_path] = mtime
                return cls._config_cache[config_path]
        except Exception as e:
            logger.error(f"❌ 加载配置文件失败: {config_path}, 错误: {e}")
            return {}

    @classmethod
    def get_agent_config(cls, slug_or_name: str, config_path: str = None) -> Optional[Dict[str, Any]]:
        """
        根据 slug 或中文名称获取特定智能体的配置
        
        Args:
            slug_or_name: 智能体标识符（slug）或中文名称（name）
            config_path: 配置文件路径 (可选)
            
        Returns:
            智能体配置字典，如果未找到则返回 None
        """
        config = cls.load_config(config_path)
        
        # 检查 customModes - 先按 slug 查找，再按 name 查找
        for agent in config.get('customModes', []):
            if agent.get('slug') == slug_or_name:
                return agent
            if agent.get('name') == slug_or_name:
                return agent
                
        # 检查 agents (如果配置结构不同)
        for agent in config.get('agents', []):
            if agent.get('slug') == slug_or_name:
                return agent
            if agent.get('name') == slug_or_name:
                return agent
                
        return None

    @classmethod
    def get_slug_by_name(cls, name: str, config_path: str = None) -> Optional[str]:
        """
        根据中文名称获取对应的 slug
        
        Args:
            name: 智能体中文名称
            config_path: 配置文件路径 (可选)
            
        Returns:
            对应的 slug，如果未找到则返回 None
        """
        config = cls.load_config(config_path)
        
        # 检查 customModes
        for agent in config.get('customModes', []):
            if agent.get('name') == name:
                return agent.get('slug')
                
        # 检查 agents
        for agent in config.get('agents', []):
            if agent.get('name') == name:
                return agent.get('slug')
                
        return None

    @classmethod
    def get_all_agents(cls, config_path: str = None) -> List[Dict[str, Any]]:
        """
        获取所有配置的智能体列表
        
        Args:
            config_path: 配置文件路径 (可选)
            
        Returns:
            智能体配置列表
        """
        config = cls.load_config(config_path)
        agents = []
        
        # 从 customModes 获取
        agents.extend(config.get('customModes', []))
        
        # 从 agents 获取（如果配置结构不同）
        agents.extend(config.get('agents', []))
        
        return agents

    @classmethod
    def build_lookup_map(cls, config_path: str = None) -> Dict[str, Dict[str, Any]]:
        """
        构建一个查找映射，支持通过多种方式查找智能体配置
        
        映射的 key 包括：
        - slug (如 "market-analyst")
        - 简短 ID (如 "market"，从 slug 派生)
        - 中文名称 (如 "市场技术分析师")
        
        Returns:
            Dict[str, Dict] - key 为各种标识符，value 为包含 internal_key, slug, tool_key 的字典
        """
        agents = cls.get_all_agents(config_path)
        lookup = {}
        
        for agent in agents:
            slug = agent.get('slug', '')
            name = agent.get('name', '')
            
            if not slug:
                continue
            
            # 生成 internal_key（去除 -analyst 后缀，替换 - 为 _）
            internal_key = slug.replace("-analyst", "").replace("-", "_")
            
            # 根据 slug 推断工具类型
            tool_key = cls._infer_tool_key(slug, name)
            
            # 构建配置信息
            config_info = {
                'internal_key': internal_key,
                'slug': slug,
                'tool_key': tool_key,
                'name': name,
                'display_name': internal_key.replace('_', ' ').title()
            }
            
            # 添加多种查找方式
            lookup[slug] = config_info  # 完整 slug
            lookup[internal_key] = config_info  # 简短 ID
            if name:
                lookup[name] = config_info  # 中文名称
        
        return lookup

    @classmethod
    def _infer_tool_key(cls, slug: str, name: str = "") -> str:
        """
        根据 slug 和名称推断应该使用的工具类型
        
        Args:
            slug: 智能体 slug
            name: 智能体中文名称
            
        Returns:
            工具类型 key (market, news, social, fundamentals)
        """
        search_key = slug.lower()
        name_lower = name.lower() if name else ""
        
        if "news" in search_key or "新闻" in name:
            return "news"
        elif "social" in search_key or "sentiment" in search_key or "社交" in name or "情绪" in name:
            return "social"
        elif "fundamental" in search_key or "基本面" in name:
            return "fundamentals"
        else:
            # 默认使用 market 工具
            return "market"

    @classmethod
    def _get_analyst_icon(cls, slug: str, name: str = "") -> str:
        """
        根据 slug 和名称推断分析师图标
        
        Args:
            slug: 智能体 slug
            name: 智能体中文名称
            
        Returns:
            图标 emoji
        """
        search_key = slug.lower()
        
        if "news" in search_key or "新闻" in name:
            return "📰"
        elif "social" in search_key or "sentiment" in search_key or "社交" in name or "情绪" in name:
            return "💬"
        elif "fundamental" in search_key or "基本面" in name:
            return "💼"
        elif "china" in search_key or "中国" in name:
            return "🇨🇳"
        elif "capital" in search_key or "资金" in name:
            return "💸"
        elif "market" in search_key or "市场" in name or "技术" in name:
            return "📊"
        else:
            return "🤖"

    @classmethod
    def build_node_mapping(cls, config_path: str = None) -> Dict[str, Optional[str]]:
        """
        动态构建节点名称映射表，用于进度更新
        
        映射 LangGraph 节点名称到中文显示名称
        
        Returns:
            Dict[str, Optional[str]] - key 为节点名称，value 为中文显示名称（None 表示跳过）
        """
        agents = cls.get_all_agents(config_path)
        node_mapping = {}
        
        for agent in agents:
            slug = agent.get('slug', '')
            name = agent.get('name', '')
            
            if not slug:
                continue
            
            # 生成 internal_key（去除 -analyst 后缀，替换 - 为 _）
            internal_key = slug.replace("-analyst", "").replace("-", "_")
            
            # 生成节点名称（首字母大写，如 "China_Market Analyst"）
            formatted_name = internal_key.replace('_', ' ').title().replace(' ', '_')
            analyst_node_name = f"{formatted_name} Analyst"
            
            # 获取图标
            icon = cls._get_analyst_icon(slug, name)
            
            # 添加分析师节点映射
            node_mapping[analyst_node_name] = f"{icon} {name}"
            
            # 添加工具节点映射（跳过）
            node_mapping[f"tools_{internal_key}"] = None
            
            # 添加消息清理节点映射（跳过）
            node_mapping[f"Msg Clear {formatted_name}"] = None
        
        # 添加固定的非分析师节点映射
        node_mapping.update({
            # 研究员节点
            'Bull Researcher': "🐂 看涨研究员",
            'Bear Researcher': "🐻 看跌研究员",
            'Research Manager': "👔 研究经理",
            # 交易员节点
            'Trader': "💼 交易员决策",
            # 风险评估节点
            'Risky Analyst': "🔥 激进风险评估",
            'Safe Analyst': "🛡️ 保守风险评估",
            'Neutral Analyst': "⚖️ 中性风险评估",
            'Risk Judge': "🎯 风险经理",
        })
        
        return node_mapping

    @classmethod
    def build_progress_map(cls, config_path: str = None) -> Dict[str, float]:
        """
        动态构建进度映射表，用于进度百分比计算
        
        Returns:
            Dict[str, float] - key 为中文显示名称，value 为进度百分比
        """
        agents = cls.get_all_agents(config_path)
        progress_map = {}
        
        # 分析师阶段占 10% - 50%，平均分配
        analyst_count = len(agents)
        if analyst_count > 0:
            analyst_progress_range = 40  # 10% 到 50%
            progress_per_analyst = analyst_progress_range / analyst_count
            
            for i, agent in enumerate(agents):
                slug = agent.get('slug', '')
                name = agent.get('name', '')
                
                if not slug or not name:
                    continue
                
                icon = cls._get_analyst_icon(slug, name)
                display_name = f"{icon} {name}"
                
                # 计算进度百分比（从 10% 开始）
                progress = 10 + (i + 1) * progress_per_analyst
                progress_map[display_name] = round(progress, 1)
        
        # 添加固定的非分析师节点进度
        progress_map.update({
            "🐂 看涨研究员": 51.25,
            "🐻 看跌研究员": 57.5,
            "👔 研究经理": 70,
            "💼 交易员决策": 78,
            "🔥 激进风险评估": 81.75,
            "🛡️ 保守风险评估": 85.5,
            "⚖️ 中性风险评估": 89.25,
            "🎯 风险经理": 93,
            "📊 生成报告": 97,
        })
        
        return progress_map

    @classmethod
    def clear_cache(cls):
        """清除配置缓存，用于配置文件更新后重新加载"""
        cls._config_cache.clear()
        cls._config_mtime.clear()
        logger.info("🔄 已清除智能体配置缓存")

    @classmethod
    def _mcp_settings_from_toolkit(cls, toolkit):
        """
        提取 MCP 相关开关和加载器，保持与统一工具注册逻辑兼容。
        """
        enable_mcp = False
        mcp_loader = None

        if isinstance(toolkit, dict):
            enable_mcp = bool(toolkit.get("enable_mcp", False))
            mcp_loader = toolkit.get("mcp_tool_loader")
        else:
            enable_mcp = bool(getattr(toolkit, "enable_mcp", False))
            mcp_loader = getattr(toolkit, "mcp_tool_loader", None)

        return enable_mcp, mcp_loader

    @staticmethod
    def _wrap_tool_safe(tool, toolkit=None):
        """
        🛡️ 安全增强：包装工具以捕获异常，防止单个工具失败导致 Agent 崩溃。
        返回错误信息字符串供 LLM 决策，而不是抛出异常。

        集成任务级 MCP 管理器：
        - 检查工具是否被断路器禁用
        - 通过任务管理器执行工具（包含重试和并发控制）
        """
        # 获取任务级 MCP 管理器（如果存在）
        task_mcp_manager = None
        task_id = None
        if toolkit:
            if isinstance(toolkit, dict):
                task_mcp_manager = toolkit.get("task_mcp_manager")
                task_id = toolkit.get("task_id")
            else:
                task_mcp_manager = getattr(toolkit, "task_mcp_manager", None)
                task_id = getattr(toolkit, "task_id", None)

        # 获取工具的服务器名称（用于 MCP 工具识别）
        server_name = None
        tool_metadata = getattr(tool, "metadata", {}) or {}
        if isinstance(tool_metadata, dict):
            server_name = tool_metadata.get("server_name")
        if not server_name:
            server_name = getattr(tool, "server_name", None)
            if not server_name:
                server_name = getattr(tool, "_server_name", None)

        # 判断是否为 MCP 工具（有服务器名称的视为外部 MCP 工具）
        is_mcp_tool = server_name is not None and server_name != "local"

        # 同步方法包装
        if hasattr(tool, "func") and callable(tool.func):
            original_func = tool.func
            tool_name = getattr(tool, "name", "unknown")

            def safe_func(*args, **kwargs):
                try:
                    # 如果是 MCP 工具且有任务管理器，使用任务管理器执行
                    if is_mcp_tool and task_mcp_manager:
                        # 使用任务管理器执行（包含断路器、重试、并发控制）
                        import asyncio
                        try:
                            loop = asyncio.get_running_loop()
                        except RuntimeError:
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)

                        # 检查工具是否可用
                        async def check_and_execute():
                            # 检查断路器状态
                            if not await task_mcp_manager.is_tool_available(tool_name, server_name):
                                return {
                                    "status": "disabled",
                                    "message": f"工具 {tool_name} 在当前任务中已禁用（连续失败或断路器打开）",
                                    "tool_name": tool_name
                                }

                            # 通过任务管理器执行
                            return await task_mcp_manager.execute_tool(
                                tool_name,
                                original_func,
                                *args,
                                server_name=server_name,
                                **kwargs
                            )

                        # 在同步环境中运行异步函数
                        if loop.is_running():
                            # 使用 asyncio.run_coroutine_threadsafe
                            import concurrent.futures
                            from concurrent.futures import ThreadPoolExecutor
                            with ThreadPoolExecutor(max_workers=1) as executor:
                                future = executor.submit(asyncio.run, check_and_execute())
                                result = future.result()
                                # 检查是否为错误状态
                                if isinstance(result, dict) and result.get("status") in ["error", "disabled"]:
                                    error_msg = f"❌ [系统提示] {result.get('message', '工具调用失败')}\n👉 请不要停止分析！\n1. 如果有其他工具可用，请尝试其他工具。\n2. 如果无法解决，请在最终报告中明确记录此错误和失败原因。"
                                    logger.warning(f"⚠️ [MCP断路器] 工具 {tool_name} 返回: {result.get('status')}")
                                    return error_msg
                                return result
                        else:
                            result = asyncio.run(check_and_execute())
                            if isinstance(result, dict) and result.get("status") in ["error", "disabled"]:
                                error_msg = f"❌ [系统提示] {result.get('message', '工具调用失败')}\n👉 请不要停止分析！\n1. 如果有其他工具可用，请尝试其他工具。\n2. 如果无法解决，请在最终报告中明确记录此错误和失败原因。"
                                logger.warning(f"⚠️ [MCP断路器] 工具 {tool_name} 返回: {result.get('status')}")
                                return error_msg
                            return result

                    # 非 MCP 工具或无任务管理器，使用原有的执行逻辑
                    # 🛡️ 兼容性增强：检测当前是否在 uvloop/asyncio 循环中
                    import asyncio
                    try:
                        loop = asyncio.get_running_loop()
                        is_loop_running = True
                    except RuntimeError:
                        is_loop_running = False

                    if is_loop_running:
                        # 如果有循环运行（特别是 uvloop），则必须使用线程隔离
                        from concurrent.futures import ThreadPoolExecutor
                        with ThreadPoolExecutor(max_workers=1) as executor:
                            future = executor.submit(original_func, *args, **kwargs)
                            return future.result()
                    else:
                        return original_func(*args, **kwargs)

                except Exception as e:
                    # 捕获异常并返回友好的错误提示
                    error_msg = f"❌ [系统提示] 工具 '{tool_name}' 调用失败: {str(e)}。\n👉 请不要停止分析！\n1. 如果有其他工具可用，请尝试其他工具。\n2. 如果无法解决，请在最终报告中明确记录此错误和失败原因。"
                    logger.error(f"⚠️ [工具安全网] 捕获到工具异常: {tool_name} -> {e}")
                    return error_msg

            tool.func = safe_func

        # 异步方法包装 (如果有)
        if hasattr(tool, "coroutine") and callable(tool.coroutine):
            original_coro = tool.coroutine
            tool_name = getattr(tool, "name", "unknown")

            async def safe_coro(*args, **kwargs):
                try:
                    # 如果是 MCP 工具且有任务管理器，使用任务管理器执行
                    if is_mcp_tool and task_mcp_manager:
                        # 检查并执行
                        if not await task_mcp_manager.is_tool_available(tool_name, server_name):
                            return {
                                "status": "disabled",
                                "message": f"工具 {tool_name} 在当前任务中已禁用（连续失败或断路器打开）",
                                "tool_name": tool_name
                            }

                        return await task_mcp_manager.execute_tool(
                            tool_name,
                            original_coro,
                            *args,
                            server_name=server_name,
                            **kwargs
                        )

                    # 非 MCP 工具直接执行
                    return await original_coro(*args, **kwargs)
                except Exception as e:
                    error_msg = f"❌ [系统提示] 工具 '{tool_name}' (Async) 调用失败: {str(e)}。\n👉 请不要停止分析！\n1. 如果有其他工具可用，请尝试其他工具。\n2. 如果无法解决，请在最终报告中明确记录此错误和失败原因。"
                    logger.error(f"⚠️ [工具安全网] 捕获到工具异常(Async): {tool_name} -> {e}")
                    return error_msg

            tool.coroutine = safe_coro

        return tool

    @classmethod
    def create_analyst(cls, slug: str, llm: Any, toolkit: Any, config_path: str = None) -> Callable:
        """
        创建动态分析师节点函数

        🔥 [已废弃] 请使用 create_react_agent_subgraph() 替代

        此方法使用 GenericAgent 包装，旧架构存在工具调用流程控制问题。
        新的子图模式更符合 LangGraph 最佳实践。

        Args:
            slug: 智能体标识符 (如 "market-analyst")
            llm: LLM 实例
            toolkit: 工具集
            config_path: 配置文件路径 (可选)

        Returns:
            LangGraph 节点函数
        """
        agent_config = cls.get_agent_config(slug, config_path)
        if not agent_config:
            raise ValueError(f"未找到智能体配置: {slug}")
            
        name = agent_config.get("name", slug)
        role_definition = agent_config.get("roleDefinition", "")
        
        logger.info(f"🤖 创建动态智能体: {name} ({slug})")
        
        # 获取工具
        enable_mcp, mcp_loader = cls._mcp_settings_from_toolkit(toolkit)
        
        # 根据 slug 或配置筛选工具；默认全量
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
                logger.info(f"🔧 工具已按配置裁剪: {len(tools)}/{len(allowed_set)} 个匹配")
            else:
                logger.warning(
                    "⚠️ 工具裁剪后为空，回退到全量工具。"
                    "请确认配置的工具名称与注册名称一致。"
                )
        
        # 🛡️ 安全增强：包装所有工具以捕获异常
        # 这样即使单个工具崩溃，Agent 也能收到错误信息并继续执行
        # 传递 toolkit 以支持任务级 MCP 管理
        tools = [cls._wrap_tool_safe(tool, toolkit) for tool in tools]

        # 实例化通用智能体
        agent = GenericAgent(
            name=name,
            slug=slug,
            llm=llm,
            tools=tools,
            system_message_template=role_definition
        )

        # 创建闭包函数作为节点
        # 使用 log_analyst_module 装饰器，模块名使用 slug 的简化版（去除 -analyst 后缀）
        module_name = slug.replace("-analyst", "").replace("-", "_")
        
        @log_analyst_module(module_name)
        def dynamic_analyst_node(state):
            return agent.run(state)

        return dynamic_analyst_node

# ============================================================================
# 便捷工厂函数
# 🔥 [已废弃] 请使用 create_react_agent_subgraph() 替代
# ============================================================================

def create_dynamic_analyst(slug: str, llm: Any, toolkit: Any) -> Callable:
    """
    创建动态分析师节点函数（旧模式）。

    🔥 [已废弃] 请使用 create_react_agent_subgraph() 替代

    旧模式使用 GenericAgent 包装 create_react_agent，存在以下问题：
    1. 工具调用循环在节点内部完成，父工作流无法控制
    2. 外部条件边永远不会被触发
    3. 外部 ToolNode 永远不会被使用

    新模式（子图模式）优势：
    - 子图直接作为节点添加到父工作流
    - LangGraph 自动处理子图与父图的状态通信
    - 工具调用循环由子图内部控制，符合 LangGraph 最佳实践
    """
    return DynamicAnalystFactory.create_analyst(slug, llm, toolkit)


# ============================================================================
# 子图模式工厂函数（LangGraph官方推荐方式）
# ============================================================================

def create_react_agent_subgraph(slug: str, llm: Any, toolkit: Any):
    """
    创建ReAct Agent子图（编译后的StateGraph），直接作为节点添加到父工作流。

    这是LangGraph官方推荐的多智能体架构模式：
    - 每个分析师是一个独立的ReAct Agent子图
    - 子图内部控制工具调用流程（agent → tools → agent循环）
    - 父工作流只控制分析师之间的顺序

    Args:
        slug: 智能体标识符（如 "market-analyst"）
        llm: LLM实例
        toolkit: 工具配置

    Returns:
        编译后的StateGraph（可直接作为节点添加到父工作流）

    参考: https://docs.langchain.com/oss/python/langgraph/use-subgraphs
    """
    from langgraph.prebuilt import create_react_agent
    from tradingagents.agents.utils.agent_states import AgentState
    from langgraph.graph import StateGraph, END

    # 1. 加载YAML配置
    agent_config = DynamicAnalystFactory.get_agent_config(slug)
    if not agent_config:
        raise ValueError(f"未找到智能体配置: {slug}")

    name = agent_config.get("name", slug)
    role_definition = agent_config.get("roleDefinition", "")

    logger.info(f"🤖 [子图工厂] 创建ReAct Agent子图: {name} ({slug})")

    # 2. 加载工具（与原逻辑保持一致）
    enable_mcp, mcp_loader = DynamicAnalystFactory._mcp_settings_from_toolkit(toolkit)

    tools = get_all_tools(
        toolkit=toolkit,
        enable_mcp=enable_mcp,
        mcp_tool_loader=mcp_loader
    )

    # 根据配置筛选工具白名单
    allowed_tool_names = agent_config.get("tools") or []
    if allowed_tool_names:
        allowed_set = {str(name).strip() for name in allowed_tool_names if str(name).strip()}
        filtered_tools = [
            tool for tool in tools
            if getattr(tool, "name", None) in allowed_set
        ]
        if filtered_tools:
            tools = filtered_tools
            logger.info(f"🔧 [子图工厂] 工具已按配置裁剪: {len(tools)}/{len(allowed_set)} 个匹配")
        else:
            logger.warning("⚠️ [子图工厂] 工具裁剪后为空，回退到全量工具")

    # 3. 安全包装工具
    tools = [DynamicAnalystFactory._wrap_tool_safe(tool, toolkit) for tool in tools]

    # 4. 🔥 修复：定义子图状态（必须在 create_react_agent 调用之前）
    # 子图状态继承自父图的 AgentState，包含所有自定义字段
    from langgraph.graph import StateGraph

    class SubgraphState(AgentState):
        """子图状态，继承自父图的AgentState"""
        pass

    # 5. 🔥 修复：使用 pre_model_hook 实现动态系统提示词（LangGraph 官方推荐方式）
    # 参考: https://langchain-ai.github.io/langgraph/how-tos/create-react-agent-manage-message-history/
    from langchain_core.messages import SystemMessage, HumanMessage, RemoveMessage

    def _generate_system_prompt(role_definition: str, ticker: str, current_date: str) -> str:
        """
        生成系统提示词的辅助函数。

        Args:
            role_definition: 从配置文件加载的角色定义
            ticker: 股票代码
            current_date: 交易日期

        Returns:
            str: 完整的系统提示词
        """
        # 处理空值情况
        if not ticker:
            logger.warning("⚠️ [系统提示词] ticker 为空，使用占位符")
            ticker = "{stock_code}"
        if not current_date:
            logger.warning("⚠️ [系统提示词] current_date 为空，使用当前时间")
            from datetime import datetime
            current_date = datetime.now().strftime("%Y-%m-%d")

        # 获取市场信息和公司名称
        from tradingagents.utils.stock_utils import StockUtils
        market_info = StockUtils.get_market_info(ticker)

        company_name = ticker  # 默认使用ticker
        if market_info["is_china"]:
            from tradingagents.dataflows.interface import get_china_stock_info_unified
            try:
                stock_info = get_china_stock_info_unified(ticker)
                if "股票名称:" in stock_info:
                    company_name = stock_info.split("股票名称:")[1].split("\n")[0].strip()
            except Exception:
                pass
        elif market_info["is_hk"]:
            try:
                from tradingagents.dataflows.providers.hk.improved_hk import get_hk_company_name_improved
                company_name = get_hk_company_name_improved(ticker)
            except Exception:
                clean_ticker = ticker.replace(".HK", "").replace(".hk", "")
                company_name = f"港股{clean_ticker}"
        elif market_info["is_us"]:
            us_stock_names = {
                "AAPL": "苹果公司", "TSLA": "特斯拉", "NVDA": "英伟达",
                "MSFT": "微软", "GOOGL": "谷歌", "AMZN": "亚马逊",
            }
            company_name = us_stock_names.get(ticker.upper(), f"美股{ticker}")

        # 替换占位符
        system_msg_content = role_definition
        system_msg_content = system_msg_content.replace("{current_date}", str(current_date))
        system_msg_content = system_msg_content.replace("{ticker}", str(ticker))
        system_msg_content = system_msg_content.replace("{company_name}", str(company_name))

        # 补充上下文信息
        context_info = (
            f"\n\n当前上下文信息:\n"
            f"当前日期: {current_date}\n"
            f"股票代码: {ticker}\n"
            f"公司名称: {company_name}\n"
            f"请用中文回答。\n\n"
            f"⚠️ 重要指令：\n"
            f"1. 如果工具调用失败（返回错误信息），请在报告中如实记录失败原因，**严禁编造**虚假数据。\n"
            f"2. 即使没有获取到完整数据，也请根据已知信息生成一份包含【错误说明】的报告。\n"
            f"3. 你的报告将被用于最终汇总，请确保信息的真实性和准确性。\n"
            f"4. **禁止死循环**：\n"
            f"   - 每次调用工具前，请仔细检查上方对话历史。\n"
            f"   - **严禁**使用完全相同的参数连续两次调用同一个工具。\n"
            f"   - 如果连续 3 次尝试均未获得有效信息，请立即停止尝试。\n"
            f"5. **最终输出**：必须包含具体的分析结论，不要只列出数据。\n"
        )
        system_msg_content += context_info

        return system_msg_content

    def pre_model_hook_impl(state: AgentState):
        """
        pre_model_hook: 在每次 LLM 调用前执行，用于动态生成系统提示词和初始任务消息。

        这是 LangGraph 官方推荐的方式，用于在 ReAct Agent 中管理消息历史。
        通过返回 llm_input_messages，可以控制每次 LLM 调用时接收的消息内容。

        Token 优化：只在第一次调用时添加完整系统提示词，后续调用可以省略。
        """
        # 获取关键状态
        current_date = state.get("trade_date", "")
        ticker = state.get("company_of_interest", "")

        # 获取当前消息列表
        messages = list(state.get("messages", []))

        # 🔥 调试日志
        logger.debug(f"🔍 [pre_model_hook] trade_date={current_date}, company_of_interest={ticker}")
        logger.debug(f"🔍 [pre_model_hook] 当前消息数量: {len(messages)}")

        # 生成系统提示词
        system_prompt = _generate_system_prompt(
            role_definition, ticker, current_date
        )

        # 🔥 修复：检测是否需要替换初始消息
        # 父图传入的消息是：HumanMessage("请分析 {company_name}，交易日期为 {trade_date}。")
        # 我们需要根据 initial_task 配置生成更具体的初始消息
        if len(messages) <= 1:
            # 第一次调用：需要添加/替换初始消息

            # 🔥 读取 initial_task 配置
            agent_config = DynamicAnalystFactory.get_agent_config(slug)
            initial_task = agent_config.get("initial_task", "") if agent_config else ""

            # 获取公司名称（复用 _generate_system_prompt 中的逻辑）
            from tradingagents.utils.stock_utils import StockUtils
            market_info = StockUtils.get_market_info(ticker)
            company_name = ticker  # 默认

            if market_info["is_china"]:
                from tradingagents.dataflows.interface import get_china_stock_info_unified
                try:
                    stock_info = get_china_stock_info_unified(ticker)
                    if "股票名称:" in stock_info:
                        company_name = stock_info.split("股票名称:")[1].split("\n")[0].strip()
                except Exception:
                    pass
            elif market_info["is_hk"]:
                try:
                    from tradingagents.dataflows.providers.hk.improved_hk import get_hk_company_name_improved
                    company_name = get_hk_company_name_improved(ticker)
                except Exception:
                    clean_ticker = ticker.replace(".HK", "").replace(".hk", "")
                    company_name = f"港股{clean_ticker}"
            elif market_info["is_us"]:
                us_stock_names = {
                    "AAPL": "苹果公司", "TSLA": "特斯拉", "NVDA": "英伟达",
                    "MSFT": "微软", "GOOGL": "谷歌", "AMZN": "亚马逊",
                }
                company_name = us_stock_names.get(ticker.upper(), f"美股{ticker}")

            # 定义默认任务描述
            DEFAULT_INITIAL_TASK = "请对股票进行分析"

            # 使用配置的任务描述或默认值
            task_description = initial_task if initial_task else DEFAULT_INITIAL_TASK

            # 拼接股票信息：用户配置 + "。股票代码：xxx，公司名称：xxx，交易日期：xxx"
            full_message = f"{task_description}。股票代码：{ticker}，公司名称：{company_name}，交易日期：{current_date}"

            logger.info(f"📝 [pre_model_hook] 使用配置的任务描述: {task_description}")
            logger.debug(f"📝 [pre_model_hook] 生成初始消息: {full_message}")

            # 🔥 关键修复：始终使用基于 initial_task 的消息
            # 如果父图传入了初始消息，替换它；如果没有，创建它
            messages = [HumanMessage(content=full_message)]

            # 在消息前面插入系统提示词
            llm_input_messages = [SystemMessage(content=system_prompt)] + messages
            logger.debug(f"📝 [pre_model_hook] 第一次调用，添加完整系统提示词（~{len(system_prompt)} tokens）")
        else:
            # 后续调用：不添加系统提示词，节省 token
            # LLM 仍然可以从之前的对话历史中理解任务
            llm_input_messages = messages
            logger.debug(f"📝 [pre_model_hook] 后续调用，跳过系统提示词（节省 ~{len(system_prompt)} tokens）")

        # 返回 llm_input_messages，这将是 LLM 的输入
        # 注意：使用 llm_input_messages 不会修改 state["messages"]
        return {"llm_input_messages": llm_input_messages}

    # 5. 使用 create_react_agent 创建子图
    # 🔥 使用 pre_model_hook 替代 prompt 参数（官方推荐方式）
    # 🔥 关键修复：必须传递 state_schema 参数，否则 LangGraph 使用默认的 AgentState（只包含 messages 和 remaining_steps）
    # 这会导致 company_of_interest 和 trade_date 无法传递到 pre_model_hook
    raw_subgraph = create_react_agent(
        model=llm,
        tools=tools,
        pre_model_hook=pre_model_hook_impl,  # 使用 pre_model_hook
        state_schema=SubgraphState,  # 🔥 关键：传递自定义的 state_schema，包含 company_of_interest 和 trade_date
    )

    # 6. 创建报告提取包装器
    # 子图执行完成后，从messages中提取报告并更新状态
    def extract_report_node(state: AgentState):
        """
        从子图生成的消息中提取报告，更新状态。

        这个节点在每个分析师子图执行后运行，确保报告被正确提取。
        """
        messages = state.get("messages", [])
        if not messages:
            return {}

        # 找到最后一条AI消息作为报告
        last_message = messages[-1]

        # 只处理AI消息
        from langchain_core.messages import AIMessage
        if not isinstance(last_message, AIMessage):
            return {}

        # 提取报告内容
        report_content = last_message.content

        # 获取internal_key（用于生成report_key）
        # 从slug生成：例如 "market-analyst" -> "market"
        internal_key = slug.replace("-analyst", "").replace("-", "_")
        report_key = f"{internal_key}_report"

        # 构造状态更新
        result = {
            report_key: report_content,
            "reports": {report_key: report_content}
        }

        logger.info(f"📝 [报告提取] {name}: 提取报告到 state['{report_key}']")

        return result

    # 7. 🔥 修复：创建简化的复合子图（使用 pre_model_hook，无需额外的状态注入节点）
    # 结构简化为：agent → extract_report → END
    # pre_model_hook 会在每次 LLM 调用前自动执行，无需单独的注入节点

    # 创建包装子图（SubgraphState 已在上面定义）
    wrapper_builder = StateGraph(SubgraphState)

    # 添加 agent 节点（内部已包含 pre_model_hook）
    wrapper_builder.add_node("agent", raw_subgraph)
    # 添加报告提取节点
    wrapper_builder.add_node("extract_report", extract_report_node)

    # 🔥 简化入口点：直接从 agent 开始
    wrapper_builder.set_entry_point("agent")

    # 添加边：agent → extract_report → END
    wrapper_builder.add_edge("agent", "extract_report")
    wrapper_builder.add_edge("extract_report", END)

    # 编译子图
    subgraph = wrapper_builder.compile()

    logger.info(f"✅ [子图工厂] 子图创建完成: {name} ({len(tools)} 个工具，使用 pre_model_hook 和报告提取)")

    return subgraph
