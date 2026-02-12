
import os
import yaml
import logging
from typing import List, Dict, Any, Optional

from tradingagents.tools.registry import get_all_tools
from tradingagents.utils.logging_init import get_logger

logger = get_logger("analysts.dynamic")

# ============================================================================
# 全局进度管理器
# ============================================================================

class ProgressManager:
    """
    全局进度管理器

    用于在节点函数和父图之间传递进度信息。
    由于 progress_callback 无法序列化，不能通过状态传递，
    所以使用全局变量来实现进度追踪。
    """

    _callback = None
    _current_node = None
    _node_start_time = None

    @classmethod
    def set_callback(cls, callback):
        """设置进度回调函数"""
        cls._callback = callback

    @classmethod
    def clear_callback(cls):
        """清除进度回调函数"""
        cls._callback = None
        cls._current_node = None
        cls._node_start_time = None

    @classmethod
    def node_start(cls, display_name):
        """节点开始执行时调用

        Args:
            display_name: 中文显示名称（如 "📊 基本面分析师"）
        """
        cls._current_node = display_name
        import time
        cls._node_start_time = time.time()
        logger.info(f"🚀 [节点] {display_name} 开始执行")

        # 立即发送进度更新
        if cls._callback:
            try:
                cls._callback(display_name)
            except Exception as e:
                logger.warning(f"⚠️ 进度回调失败: {e}")

    @classmethod
    def node_end(cls, name):
        """节点执行完成时调用"""
        import time
        elapsed = time.time() - cls._node_start_time if cls._node_start_time else 0
        logger.info(f"✅ [节点] {name} 执行完成，耗时: {elapsed:.2f}秒")
        cls._current_node = None
        cls._node_start_time = None

    @classmethod
    def get_current_node(cls):
        """获取当前正在执行的节点名称"""
        return cls._current_node


# 保留旧名称作为别名，向后兼容
SubgraphProgressManager = ProgressManager


class DynamicAnalystFactory:
    """
    动态分析师工厂工具类

    提供配置加载、查找、映射等工具函数，被 SimpleAgentFactory 使用。
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
                    logger.warning(f"⚠️ 未找到配置文件: {config_path_candidate}")

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
        根据 slug、internal_key 或中文名称获取特定智能体的配置

        支持三种查找方式：
        - slug: 如 "market-analyst"
        - internal_key: 如 "market"（从 slug 派生：去除 -analyst 后缀，替换 - 为 _）
        - name: 如 "市场技术分析师"

        Args:
            slug_or_name: 智能体标识符（slug、internal_key）或中文名称（name）
            config_path: 配置文件路径 (可选)

        Returns:
            智能体配置字典，如果未找到则返回 None
        """
        config = cls.load_config(config_path)

        # 合并 customModes 和 agents 列表
        all_agents = config.get('customModes', []) + config.get('agents', [])

        for agent in all_agents:
            slug = agent.get('slug', '')
            name = agent.get('name', '')

            # 生成 internal_key（从 slug 派生：去除 -analyst 后缀，替换 - 为 _）
            internal_key = slug.replace("-analyst", "").replace("-", "_")

            # 支持三种查找方式
            if slug == slug_or_name:
                return agent
            if internal_key == slug_or_name:
                return agent
            if name == slug_or_name:
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
        from typing import Optional

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
    def build_progress_map(cls, selected_analysts: List[str] = None, config_path: str = None) -> Dict[str, float]:
        """
        动态构建进度映射表，用于进度百分比计算

        Args:
            selected_analysts: 选择的智能体列表（slug、internal_key 或中文名称）
                              如果提供，则基于选择的智能体计算进度
                              如果为 None，则回退到所有配置的智能体
            config_path: 配置文件路径 (可选)

        Returns:
            Dict[str, float] - key 为中文显示名称，value 为进度百分比
        """
        progress_map = {}

        # 确定要计算进度的智能体列表
        if selected_analysts:
            # 基于选择的智能体计算进度
            agents = []
            for analyst_id in selected_analysts:
                agent_config = cls.get_agent_config(analyst_id, config_path)
                if agent_config:
                    agents.append(agent_config)
                else:
                    logger.warning(f"⚠️ 构建进度映射时未找到智能体配置: {analyst_id}")
        else:
            # 回退到所有配置的智能体
            agents = cls.get_all_agents(config_path)

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
        提取 MCP 相关开关和加载器
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
        包装工具以支持 MCP 断路器功能
        """
        # 获取任务级 MCP 管理器（如果存在）
        task_mcp_manager = None
        if toolkit:
            if isinstance(toolkit, dict):
                task_mcp_manager = toolkit.get("task_mcp_manager")
            else:
                task_mcp_manager = getattr(toolkit, "task_mcp_manager", None)

        # 获取工具的服务器名称（用于 MCP 工具识别）
        server_name = None
        tool_metadata = getattr(tool, "metadata", {}) or {}
        if isinstance(tool_metadata, dict):
            server_name = tool_metadata.get("server_name")
        if not server_name:
            server_name = getattr(tool, "server_name", None)
            if not server_name:
                server_name = getattr(tool, "_server_name", None)

        # 判断是否为外部 MCP 工具（有服务器名称且不是 "local"）
        is_external_mcp_tool = server_name is not None and server_name != "local"

        # 只有外部 MCP 工具需要断路器检查
        if not is_external_mcp_tool or not task_mcp_manager:
            return tool  # 本地工具直接返回，不做包装

        tool_name = getattr(tool, "name", "unknown")

        # 同步方法包装（仅外部 MCP 工具）
        if hasattr(tool, "func") and callable(tool.func):
            original_func = tool.func

            def safe_func(*args, **kwargs):
                import asyncio

                async def check_and_execute():
                    # 检查断路器状态
                    if not await task_mcp_manager.is_tool_available(tool_name, server_name):
                        return {
                            "status": "disabled",
                            "message": f"工具 {tool_name} 在当前任务中已禁用（连续失败或断路器打开）",
                            "tool_name": tool_name
                        }

                    # 通过任务管理器执行（包含重试和并发控制）
                    return await task_mcp_manager.execute_tool(
                        tool_name,
                        original_func,
                        server_name=server_name,
                        *args,
                        **kwargs
                    )

                # 在同步环境中运行异步函数 - 使用独立线程隔离事件循环，避免死锁
                import threading
                result_container = {}

                def run_in_thread():
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    try:
                        result_container['result'] = new_loop.run_until_complete(check_and_execute())
                    except Exception as e:
                        result_container['error'] = e
                    finally:
                        new_loop.close()

                # 启动独立线程运行异步任务
                t = threading.Thread(target=run_in_thread)
                t.start()
                t.join()  # 等待线程结束

                if 'error' in result_container:
                    error = result_container['error']
                    logger.error(f"⚠️ [MCP断路器] 工具 {tool_name} 执行异常: {error}")
                    return f"❌ 工具 {tool_name} 执行出错: {str(error)}"

                result = result_container.get('result')

                # 检查是否为错误状态
                if isinstance(result, dict) and result.get("status") in ["error", "disabled"]:
                    logger.warning(f"⚠️ [MCP断路器] 工具 {tool_name} 返回: {result.get('status')}")
                    return f"❌ 工具 {tool_name} 不可用: {result.get('message', '未知错误')}\n请尝试其他工具继续分析。"
                return result

            tool.func = safe_func

        # 异步方法包装（仅外部 MCP 工具）
        if hasattr(tool, "coroutine") and callable(tool.coroutine):
            original_coro = tool.coroutine

            async def safe_coro(*args, **kwargs):
                # 检查并执行
                if not await task_mcp_manager.is_tool_available(tool_name, server_name):
                    return f"❌ 工具 {tool_name} 在当前任务中已禁用（断路器打开）\n请尝试其他工具继续分析。"

                return await task_mcp_manager.execute_tool(
                    tool_name,
                    original_coro,
                    server_name=server_name,
                    *args,
                    **kwargs
                )

            tool.coroutine = safe_coro

        return tool
