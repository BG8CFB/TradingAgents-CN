
import os
import yaml
import logging
import threading
from typing import List, Dict, Any, Optional

from app.engine.tools.registry import get_all_tools
from app.utils.logging_init import get_logger

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

    使用 task_id 映射的回调字典，支持多任务并发。
    每个分析任务通过 task_id 隔离，避免并发任务互相覆盖。
    """

    _callbacks: Dict[str, Any] = {}       # task_id -> callback
    _current_nodes: Dict[str, str] = {}   # task_id -> current_node
    _node_start_times: Dict[str, float] = {}  # task_id -> start_time
    _lock = threading.Lock()

    @classmethod
    def set_callback(cls, task_id: str, callback):
        """设置指定任务的进度回调函数

        Args:
            task_id: 任务 ID，用于隔离不同任务的回调
            callback: 进度回调函数，传入 None 则移除该任务的回调
        """
        with cls._lock:
            if callback:
                cls._callbacks[task_id] = callback
            else:
                cls._callbacks.pop(task_id, None)

    @classmethod
    def remove_callback(cls, task_id: str):
        """清除指定任务的所有进度信息

        Args:
            task_id: 任务 ID
        """
        with cls._lock:
            cls._callbacks.pop(task_id, None)
            cls._current_nodes.pop(task_id, None)
            cls._node_start_times.pop(task_id, None)

    @classmethod
    def clear_callback(cls, task_id: str = None):
        """清除进度回调函数（向后兼容）

        Args:
            task_id: 任务 ID，如果为 None 则清除所有回调
        """
        with cls._lock:
            if task_id:
                cls._callbacks.pop(task_id, None)
                cls._current_nodes.pop(task_id, None)
                cls._node_start_times.pop(task_id, None)
            else:
                cls._callbacks.clear()
                cls._current_nodes.clear()
                cls._node_start_times.clear()

    @classmethod
    def node_start(cls, display_name, task_id: str = None):
        """节点开始执行时调用

        Args:
            display_name: 中文显示名称（如 "基本面分析师"）
            task_id: 任务 ID，用于并发隔离
        """
        import time
        with cls._lock:
            # 如果指定了 task_id，仅操作该任务的回调；否则使用第一个可用回调
            if task_id:
                cls._current_nodes[task_id] = display_name
                cls._node_start_times[task_id] = time.time()
                callback = cls._callbacks.get(task_id)
            else:
                # 向后兼容：使用第一个可用回调
                tid = next(iter(cls._callbacks), None)
                if tid:
                    cls._current_nodes[tid] = display_name
                    cls._node_start_times[tid] = time.time()
                    callback = cls._callbacks.get(tid)
                else:
                    callback = None

        logger.info(f"🚀 [节点] {display_name} 开始执行")

        # 立即发送进度更新（在锁外执行，避免回调耗时阻塞其他线程）
        if callback:
            try:
                callback(display_name)
            except Exception as e:
                logger.warning(f"⚠️ 进度回调失败: {e}")

    @classmethod
    def node_end(cls, name, task_id: str = None):
        """节点执行完成时调用

        Args:
            name: 节点名称
            task_id: 任务 ID
        """
        import time
        with cls._lock:
            if task_id:
                elapsed = time.time() - cls._node_start_times.pop(task_id, 0)
                cls._current_nodes.pop(task_id, None)
            else:
                tid = next(iter(cls._node_start_times), None)
                if tid:
                    elapsed = time.time() - cls._node_start_times.pop(tid, 0)
                    cls._current_nodes.pop(tid, None)
                else:
                    elapsed = 0

        logger.info(f"✅ [节点] {name} 执行完成，耗时: {elapsed:.2f}秒")

    @classmethod
    def get_current_node(cls, task_id: str = None):
        """获取指定任务当前正在执行的节点名称"""
        with cls._lock:
            if task_id:
                return cls._current_nodes.get(task_id)
            tid = next(iter(cls._current_nodes), None)
            return cls._current_nodes.get(tid) if tid else None

    @classmethod
    def get_callback(cls, task_id: str = None):
        """获取指定任务的回调函数"""
        with cls._lock:
            if task_id:
                return cls._callbacks.get(task_id)
            # 向后兼容：返回第一个可用回调
            tid = next(iter(cls._callbacks), None)
            return cls._callbacks.get(tid) if tid else None


# 保留旧名称作为别名，向后兼容
SubgraphProgressManager = ProgressManager


class DynamicAnalystFactory:
    """
    动态分析师工厂工具类

    提供配置加载、查找、映射等工具函数，被 SimpleAgentFactory 使用。
    """

    _config_cache = {}
    _config_mtime = {}
    _config_lock = threading.Lock()

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
        with cls._config_lock:
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

            # 根据 slug 推断工具类型（优先从配置读取）
            tool_key = cls._infer_tool_key(slug, name, agent_config=agent)

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
    def _infer_tool_key(cls, slug: str, name: str = "", agent_config: dict = None) -> str:
        """
        推断应该使用的工具类型，优先从配置读取

        Args:
            slug: 智能体 slug
            name: 智能体中文名称
            agent_config: 智能体配置字典（可选，优先读取 tool_key）

        Returns:
            工具类型 key (market, news, social, fundamentals)
        """
        if agent_config and agent_config.get("tool_key"):
            return agent_config["tool_key"]

        # 回退：字符串推断
        search_key = slug.lower()
        name_lower = name.lower() if name else ""

        if "news" in search_key or "新闻" in name:
            return "news"
        elif "social" in search_key or "sentiment" in search_key or "社交" in name or "情绪" in name:
            return "social"
        elif "fundamental" in search_key or "基本面" in name:
            return "fundamentals"
        else:
            return "market"

    @classmethod
    def _get_analyst_icon(cls, slug: str, name: str = "", agent_config: dict = None) -> str:
        """
        获取分析师图标，优先从配置读取

        Args:
            slug: 智能体 slug
            name: 智能体中文名称
            agent_config: 智能体配置字典（可选，优先读取 icon）

        Returns:
            图标 emoji
        """
        if agent_config and agent_config.get("icon"):
            return agent_config["icon"]

        # 回退：字符串推断
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

            # 获取图标（优先从配置读取）
            icon = cls._get_analyst_icon(slug, name, agent_config=agent)

            # 添加分析师节点映射
            node_mapping[analyst_node_name] = f"{icon} {name}"

            # 添加工具节点映射（跳过）
            node_mapping[f"tools_{internal_key}"] = None

            # 添加消息清理节点映射（跳过）
            node_mapping[f"Msg Clear {formatted_name}"] = None

        # 合并非分析师阶段的固定节点映射
        node_mapping.update(cls._get_non_analyst_mappings())

        return node_mapping

    @classmethod
    def _get_non_analyst_mappings(cls) -> Dict[str, str]:
        """获取非分析师阶段（Stage 2/3/4）的固定节点映射"""
        return {
            'Bull Researcher': "🐂 看涨研究员",
            'Bear Researcher': "🐻 看跌研究员",
            'Research Manager': "👔 研究经理",
            'Trader': "💼 交易员决策",
            'Risky Analyst': "🔥 激进风险评估",
            'Safe Analyst': "🛡️ 保守风险评估",
            'Neutral Analyst': "⚖️ 中性风险评估",
            'Risk Judge': "🎯 风险经理",
            'Summary Agent': "📊 生成报告",
        }

    @classmethod
    def build_progress_map(cls, selected_analysts: List[str] = None, config_path: str = None,
                           phase2_enabled: bool = True, phase3_enabled: bool = True) -> Dict[str, float]:
        """
        动态构建进度映射表，用于进度百分比计算

        Args:
            selected_analysts: 选择的智能体列表（slug、internal_key 或中文名称）
                              如果提供，则基于选择的智能体计算进度
                              如果为 None，则回退到所有配置的智能体
            config_path: 配置文件路径 (可选)
            phase2_enabled: 是否启用阶段2（辩论），默认 True
            phase3_enabled: 是否启用阶段3（风险评估），默认 True

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

                icon = cls._get_analyst_icon(slug, name, agent_config=agent)
                display_name = f"{icon} {name}"

                # 计算进度百分比（从 10% 开始）
                progress = 10 + (i + 1) * progress_per_analyst
                progress_map[display_name] = round(progress, 1)

        # 根据启用的阶段，动态分配剩余进度
        base = progress_map[list(progress_map.keys())[-1]] if progress_map else 50.0
        remaining = 100.0 - base

        later_stages = []
        if phase2_enabled:
            later_stages.extend([
                "🐂 看涨研究员",
                "🐻 看跌研究员",
                "👔 研究经理",
            ])
        later_stages.append("💼 交易员决策")
        if phase3_enabled:
            later_stages.extend([
                "🔥 激进风险评估",
                "🛡️ 保守风险评估",
                "⚖️ 中性风险评估",
                "🎯 风险经理",
            ])
        later_stages.append("📊 生成报告")

        stage_count = len(later_stages)
        per_stage = remaining / stage_count if stage_count > 0 else 0

        for i, stage_name in enumerate(later_stages):
            progress_map[stage_name] = round(base + (i + 1) * per_stage, 2)

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

                # 在同步环境中运行异步函数
                # 优先在当前线程直接运行（无线程开销）；仅在事件循环线程中才降级到新线程
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None

                result = None
                if loop is not None and loop.is_running():
                    # 当前线程已有运行中的事件循环，必须在新线程中隔离运行
                    import threading
                    result_container = {}

                    def run_in_thread():
                        try:
                            result_container['result'] = asyncio.run(check_and_execute())
                        except Exception as e:
                            result_container['error'] = e

                    t = threading.Thread(target=run_in_thread)
                    t.start()
                    t.join(timeout=120)
                    if t.is_alive():
                        return f"❌ 工具 {tool_name} 执行超时"

                    if 'error' in result_container:
                        error = result_container['error']
                        logger.error(f"⚠️ [MCP断路器] 工具 {tool_name} 执行异常: {error}")
                        return f"❌ 工具 {tool_name} 执行出错: {str(error)}"
                    result = result_container.get('result')
                else:
                    # 当前线程无事件循环，直接运行
                    try:
                        result = asyncio.run(check_and_execute())
                    except Exception as e:
                        logger.error(f"⚠️ [MCP断路器] 工具 {tool_name} 执行异常: {e}")
                        return f"❌ 工具 {tool_name} 执行出错: {str(e)}"

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
