"""
第一阶段智能体工厂

根据前端选择和配置文件，动态创建第一阶段智能体节点函数
"""

import os
import yaml
from typing import Dict, Any, List, Callable, Optional
from app.engine.tools.registry import get_all_tools
from app.utils.logging_init import get_logger

logger = get_logger("simple_agent_factory")


class SimpleAgentFactory:
    """
    简单智能体工厂
    
    根据前端选择和配置文件，创建第一阶段智能体节点函数
    """
    
    @staticmethod
    def load_config(config_path: str = None) -> Dict[str, Any]:
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
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                return config or {}
        except Exception as e:
            logger.error(f"❌ 加载配置文件失败: {config_path}, 错误: {e}")
            return {}
    
    @staticmethod
    def get_agent_config(slug_or_name: str, config_path: str = None) -> Optional[Dict[str, Any]]:
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
        config = SimpleAgentFactory.load_config(config_path)
        
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
    
    @staticmethod
    def get_all_agents(config_path: str = None) -> List[Dict[str, Any]]:
        """
        获取所有配置的智能体列表
        
        Args:
            config_path: 配置文件路径 (可选)
            
        Returns:
            智能体配置列表
        """
        config = SimpleAgentFactory.load_config(config_path)
        agents = []
        
        # 从 customModes 获取
        agents.extend(config.get('customModes', []))
        
        # 从 agents 获取（如果配置结构不同）
        agents.extend(config.get('agents', []))
        
        return agents
    
    @staticmethod
    def create_analysts(
        selected_analysts: List[str],
        llm: Any,
        toolkit: Any,
        max_tool_calls: int = 20
    ) -> Dict[str, Callable]:
        """
        创建第一阶段智能体节点函数
        
        Args:
            selected_analysts: 前端选择的分析师列表（slug 或 name）
            llm: LLM 实例
            toolkit: 工具配置
            max_tool_calls: 最大工具调用次数（固定为20）
        
        Returns:
            {internal_key: node_function}
        """
        config = SimpleAgentFactory.load_config()
        node_functions = {}
        seen_internal_keys = set()
        
        for input_key in selected_analysts:
            # 规范化 slug
            agent_config = SimpleAgentFactory.get_agent_config(input_key)
            if not agent_config:
                logger.warning(f"⚠️ 未找到智能体配置: {input_key}")
                continue
            
            slug = agent_config.get("slug", "")
            name = agent_config.get("name", "")
            system_prompt = agent_config.get("roleDefinition", "")
            
            # 生成 internal_key
            internal_key = slug.replace("-analyst", "").replace("-", "_")
            
            # 去重
            if internal_key in seen_internal_keys:
                logger.warning(f"⚠️ 跳过重复的分析师: {input_key} -> {internal_key}")
                continue
            seen_internal_keys.add(internal_key)
            
            logger.info(f"🤖 [工厂] 创建智能体: {name} ({slug})")
            
            # === 加载工具（复用 DynamicAnalystFactory 的逻辑） ===
            from app.engine.agents.analysts.dynamic_analyst import DynamicAnalystFactory
            
            enable_mcp, mcp_loader = DynamicAnalystFactory._mcp_settings_from_toolkit(toolkit)
            tools = get_all_tools(
                toolkit=toolkit,
                enable_mcp=enable_mcp,
                mcp_tool_loader=mcp_loader
            )
            
            # 根据配置筛选工具白名单
            # 🔥 修复 S4: 空白名单时不再静默回退，而是明确记录并保持空列表
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
                    # 🔥 修复: 白名单配置了但没有匹配的工具，这是配置错误
                    # 记录警告但仍然回退到全量工具（保持向后兼容）
                    # 但明确标记这是一个配置问题
                    logger.warning(
                        f"⚠️ [工厂] 智能体 {name} 的工具白名单配置无效！"
                        f"配置的工具 {allowed_set} 均未找到，回退到全量工具。"
                        f"请检查配置文件中的 tools 字段是否正确。"
                    )
            
            # 安全包装工具（复用 DynamicAnalystFactory 的逻辑）
            tools = [DynamicAnalystFactory._wrap_tool_safe(tool, toolkit) for tool in tools]
            
            # === 使用简单模板创建智能体 ===
            from app.engine.agents.analysts.simple_agent_template import create_simple_agent
            node_function = create_simple_agent(
                name=name,
                slug=slug,
                llm=llm,
                tools=tools,
                system_prompt=system_prompt,
                max_tool_calls=max_tool_calls  # 🔥 固定为20
            )
            
            # 保存节点函数
            node_functions[internal_key] = node_function
        
        logger.info(f"✅ [工厂] 共创建 {len(node_functions)} 个智能体节点")
        return node_functions
    
    @staticmethod
    def build_progress_map(selected_analysts: List[str] = None, config_path: str = None) -> Dict[str, float]:
        """
        构建进度映射表，用于进度百分比计算
        
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
                agent_config = SimpleAgentFactory.get_agent_config(analyst_id, config_path)
                if agent_config:
                    agents.append(agent_config)
                else:
                    logger.warning(f"⚠️ 构建进度映射时未找到智能体配置: {analyst_id}")
        else:
            # 回退到所有配置的智能体
            agents = SimpleAgentFactory.get_all_agents(config_path)
        
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
                
                # 获取图标
                icon = SimpleAgentFactory._get_analyst_icon(slug, name)
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
    
    @staticmethod
    def _get_analyst_icon(slug: str, name: str = "") -> str:
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

