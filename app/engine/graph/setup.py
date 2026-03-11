# TradingAgents/graph/setup.py

from typing import Dict, Any, Callable
from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph, START
from langgraph.prebuilt import ToolNode

from app.engine.agents.analysts.dynamic_analyst import (
    ProgressManager  # 进度管理器
)
from app.engine.agents import *
from app.engine.agents.utils.agent_states import AgentState
from app.engine.agents.utils.agent_utils import Toolkit

from .conditional_logic import ConditionalLogic

# 导入统一日志系统
from app.utils.logging_init import get_logger
logger = get_logger("default")


class GraphSetup:
    """Handles the setup and configuration of the agent graph."""

    def __init__(
        self,
        quick_thinking_llm: ChatOpenAI,
        deep_thinking_llm: ChatOpenAI,
        toolkit: Toolkit,
        tool_nodes: Dict[str, ToolNode],  # 🔥 [已废弃] 子图模式不再使用，保留参数用于向后兼容
        bull_memory,
        bear_memory,
        trader_memory,
        invest_judge_memory,
        risk_manager_memory,
        conditional_logic: ConditionalLogic,
        config: Dict[str, Any] = None,
        react_llm = None,
    ):
        """Initialize with required components."""
        self.quick_thinking_llm = quick_thinking_llm
        self.deep_thinking_llm = deep_thinking_llm
        self.toolkit = toolkit
        self.tool_nodes = tool_nodes  # 🔥 [已废弃] 不再使用，但保留以兼容接口
        self.bull_memory = bull_memory
        self.bear_memory = bear_memory
        self.trader_memory = trader_memory
        self.invest_judge_memory = invest_judge_memory
        self.risk_manager_memory = risk_manager_memory
        self.conditional_logic = conditional_logic
        self.config = config or {}
        self.react_llm = react_llm

    def _format_analyst_name(self, internal_key: str) -> str:
        """Format analyst name from internal key (e.g., 'financial_news' -> 'Financial_News').
        Must match the logic in conditional_logic.py
        """
        return internal_key.replace('_', ' ').title().replace(' ', '_')

    def setup_graph(
        self, selected_analysts=None
    ):
        """Set up and compile the agent workflow graph.

        Args:
            selected_analysts (list): List of analyst types to include.
                支持多种输入格式：
                - 简短 ID: "market", "fundamentals", "news", "social"
                - 完整 slug: "market-analyst", "fundamentals-analyst"
                - 中文名称: "市场技术分析师", "基本面分析师"
                
                所有格式都会自动从配置文件 phase1_agents_config.yaml 中查找对应的智能体配置。
        """
        if not selected_analysts:
            raise ValueError(
                "Trading Agents Graph Setup Error: no analysts selected! 请先在 phase1 配置中选择分析师。"
            )

        # 🔍 调试日志：打印传入的分析师列表
        logger.info(f"📋 [GraphSetup] 传入的分析师列表: {selected_analysts}")

        # 初始化节点字典
        analyst_nodes = {}
        delete_nodes = {}
        normalized_analysts = []

        # 使用新工厂创建所有分析师节点（统一管理，支持错误处理）
        try:
            analyst_node_functions = SimpleAgentFactory.create_analysts(
                selected_analysts=selected_analysts,
                llm=self.quick_thinking_llm,
                toolkit=self.toolkit,
                max_tool_calls=20  # 🔥 固定为20次，不从配置文件读取
            )

            # 将工厂创建的节点函数添加到 analyst_nodes
            for internal_key, node_func in analyst_node_functions.items():
                analyst_nodes[internal_key] = node_func
                delete_nodes[internal_key] = create_msg_delete()
                normalized_analysts.append(internal_key)
                logger.info(f"✅ [重构] 已创建智能体节点: {internal_key}")
        except Exception as e:
            logger.error(f"❌ [重构] 创建智能体节点失败: {e}", exc_info=True)
            raise

        # Create researcher and manager nodes (Phase 2)
        bull_researcher_node = create_bull_researcher(
            self.quick_thinking_llm, self.bull_memory
        )
        bear_researcher_node = create_bear_researcher(
            self.quick_thinking_llm, self.bear_memory
        )
        research_manager_node = create_research_manager(
            self.deep_thinking_llm, self.invest_judge_memory
        )
        # 交易员节点现在属于 Phase 2 的最后一步
        trader_node = create_trader(self.quick_thinking_llm, self.trader_memory)

        # Create risk analysis nodes (Phase 3)
        risky_analyst = create_risky_debator(self.quick_thinking_llm)
        neutral_analyst = create_neutral_debator(self.quick_thinking_llm)
        safe_analyst = create_safe_debator(self.quick_thinking_llm)
        risk_manager_node = create_risk_manager(
            self.deep_thinking_llm, self.risk_manager_memory
        )

        # 导入 Summary Agent
        from app.engine.agents.stage_4.summary_agent import create_summary_agent
        summary_node = create_summary_agent(self.quick_thinking_llm)

        # Create workflow
        workflow = StateGraph(AgentState)

        # Add analyst nodes to the graph
        for analyst_type, node in analyst_nodes.items():
            workflow.add_node(f"{self._format_analyst_name(analyst_type)} Analyst", node)
            # 🔥 性能优化：删除消息清理节点
            # 原因：子图现在只返回最后一条消息，不需要清理
            # 之前清理节点耗时 342 秒，是因为需要删除几百条消息
            # workflow.add_node(
            #     f"Msg Clear {self._format_analyst_name(analyst_type)}", delete_nodes[analyst_type]
            # )
            # 子图模式：不再添加外部工具节点
            # 子图内部控制工具调用流程

        # Create other nodes
        workflow.add_node("Bull Researcher", bull_researcher_node)
        workflow.add_node("Bear Researcher", bear_researcher_node)
        workflow.add_node("Research Manager", research_manager_node)
        workflow.add_node("Trader", trader_node)
        workflow.add_node("Risky Analyst", risky_analyst)
        workflow.add_node("Neutral Analyst", neutral_analyst)
        workflow.add_node("Safe Analyst", safe_analyst)
        workflow.add_node("Risk Judge", risk_manager_node)
        workflow.add_node("Summary Agent", summary_node)

        # Define edges（阶段开关完全由前端传入控制）
        # 顺序: Phase 2 (Research & Trader) -> Phase 3 (Risk) -> Summary
        enable_phase2 = bool(self.config.get("phase2_enabled", False))
        enable_phase3 = bool(self.config.get("phase3_enabled", False))
        # Phase 4 flag might still be passed but effectively redundant for flow control now
        # enable_phase4 = bool(self.config.get("phase4_enabled", False)) 

        # Start with the first analyst
        if not normalized_analysts:
            raise ValueError("No valid analysts found after normalization")
        first_analyst = normalized_analysts[0]
        workflow.add_edge(START, f"{self._format_analyst_name(first_analyst)} Analyst")

        # 确定 Phase 1 结束后的下一个节点
        if enable_phase2:
            next_entry_node = "Bull Researcher"
        elif enable_phase3:
            # 如果跳过 Phase 2，尝试直接进入 Phase 3（注意：可能缺少 Trader 计划）
            next_entry_node = "Risky Analyst"
        else:
            next_entry_node = "Summary Agent"

        for i, analyst_type in enumerate(normalized_analysts):
            current_analyst = f"{self._format_analyst_name(analyst_type)} Analyst"
            # 🔥 性能优化：删除消息清理节点后，直接从分析师节点连接到下一个节点

            # Connect to next analyst or to next phase entry node
            if i < len(normalized_analysts) - 1:
                next_analyst = f"{self._format_analyst_name(normalized_analysts[i+1])} Analyst"
                workflow.add_edge(current_analyst, next_analyst)
            else:
                workflow.add_edge(current_analyst, next_entry_node)

        # Phase 2: Research Debate & Trader Plan
        if enable_phase2:
            workflow.add_conditional_edges(
                "Bull Researcher",
                self.conditional_logic.should_continue_debate,
                {
                    "Bear Researcher": "Bear Researcher",
                    "Research Manager": "Research Manager",
                },
            )
            workflow.add_conditional_edges(
                "Bear Researcher",
                self.conditional_logic.should_continue_debate,
                {
                    "Bull Researcher": "Bull Researcher",
                    "Research Manager": "Research Manager",
                },
            )
            
            # Research Manager 结束后 -> Trader (生成原始计划)
            workflow.add_edge("Research Manager", "Trader")
            
            # Trader -> Phase 3 (如果启用) 或 Summary
            if enable_phase3:
                workflow.add_edge("Trader", "Risky Analyst")
            else:
                workflow.add_edge("Trader", "Summary Agent")

        # Phase 3: Risk Management
        if enable_phase3:
            workflow.add_conditional_edges(
                "Risky Analyst",
                self.conditional_logic.should_continue_risk_analysis,
                {
                    "Safe Analyst": "Safe Analyst",
                    "Risk Judge": "Risk Judge",
                },
            )
            workflow.add_conditional_edges(
                "Safe Analyst",
                self.conditional_logic.should_continue_risk_analysis,
                {
                    "Neutral Analyst": "Neutral Analyst",
                    "Risk Judge": "Risk Judge",
                },
            )
            workflow.add_conditional_edges(
                "Neutral Analyst",
                self.conditional_logic.should_continue_risk_analysis,
                {
                    "Risky Analyst": "Risky Analyst",
                    "Risk Judge": "Risk Judge",
                },
            )
            # Risk Judge 结束后 -> Summary
            workflow.add_edge("Risk Judge", "Summary Agent")

        # Summary Agent -> END
        workflow.add_edge("Summary Agent", END)

        # Compile and return
        return workflow.compile()


# ============================================================================
# 🔥 重构说明：第一阶段智能体工厂函数已迁移到
# tradingagents/agents/analysts/simple_agent_factory.py
# 和 tradingagents/agents/analysts/simple_agent_template.py
# ============================================================================
