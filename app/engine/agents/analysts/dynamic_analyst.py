
import os
import threading
import yaml
from typing import List, Dict, Any, Optional

from app.core.env import get_env
import logging

logger = logging.getLogger("analysts.dynamic")


class DynamicAnalystFactory:
    """
    动态分析师工厂工具类

    提供配置加载、查找、映射等工具函数，被 SimpleAgentFactory 使用。
    """

    _config_cache = {}
    _config_mtime = {}
    _config_lock = threading.Lock()

    # 迁移期剥离的冗余键（引擎零消费）
    _LEGACY_KEYS = ("whenToUse", "groups", "source", "initial_task")

    @classmethod
    def _normalize_mode(cls, agent: Any) -> Any:
        """归一化单个智能体配置（迁移 shim，幂等）

        - 旧 `tools` 键拆分：含 `.` 的视为 skill 入口 → skills，其余 → data_tools
        - 剥离冗余键 whenToUse/groups/source/initial_task
        """
        if not isinstance(agent, dict):
            return agent
        if "tools" in agent and "data_tools" not in agent:
            data_tools: List[str] = []
            skills: List[str] = []
            for tid in agent.get("tools") or []:
                (skills if "." in str(tid) else data_tools).append(tid)
            agent["data_tools"] = data_tools
            if skills:
                agent.setdefault("skills", skills)
            agent.pop("tools", None)
        for key in cls._LEGACY_KEYS:
            agent.pop(key, None)
        return agent

    @classmethod
    def load_config(cls, config_path: str = None) -> Dict[str, Any]:
        """加载智能体配置文件"""
        if not config_path:
            # 1. 优先使用环境变量 AGENT_CONFIG_DIR
            env_dir = get_env("AGENT_CONFIG_DIR")
            if env_dir and os.path.exists(env_dir):
                config_path = os.path.join(env_dir, "phase1_agents_config.yaml")
            else:
                # 获取当前文件所在目录，向上逐级查找 config/agents（兼容 app/engine/... 新布局）
                current_dir = os.path.dirname(os.path.abspath(__file__))
                config_path_candidate = ""
                probe = current_dir
                for _ in range(6):
                    probe = os.path.dirname(probe)
                    candidate = os.path.join(probe, "config", "agents", "phase1_agents_config.yaml")
                    if os.path.exists(candidate):
                        config_path_candidate = candidate
                        break

                # 2. 尝试使用 config/agents/phase1_agents_config.yaml
                if os.path.exists(config_path_candidate):
                    config_path = config_path_candidate
                else:
                    logger.warning(f"⚠️ 未找到配置文件: {config_path_candidate}")

        try:
            mtime = os.path.getmtime(config_path)
        except Exception as e:
            logger.debug(f"获取配置文件修改时间失败: {e}")
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
                return cls._normalize_mode(agent)
            if internal_key == slug_or_name:
                return cls._normalize_mode(agent)
            if name == slug_or_name:
                return cls._normalize_mode(agent)

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
        agents.extend(cls._normalize_mode(a) for a in config.get('customModes', []))

        # 从 agents 获取（如果配置结构不同）
        agents.extend(cls._normalize_mode(a) for a in config.get('agents', []))

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
    def clear_cache(cls):
        """清除配置缓存，用于配置文件更新后重新加载"""
        cls._config_cache.clear()
        cls._config_mtime.clear()
        logger.info("🔄 已清除智能体配置缓存")

