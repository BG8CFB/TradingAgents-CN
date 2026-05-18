# TradingAgents/graph/propagation.py

from typing import Dict, Any

# 导入统一日志系统
from app.utils.logging_init import get_logger
logger = get_logger("default")
from app.engine.agents.utils.agent_states import (
    AgentState,
    InvestDebateState,
    RiskDebateState,
)


class Propagator:
    """Handles state initialization and propagation through the graph."""

    def __init__(self, max_recur_limit=100):
        """Initialize with configuration parameters."""
        self.max_recur_limit = max_recur_limit

    def create_initial_state(
        self, company_name: str, trade_date: str, task_id: str | None = None
    ) -> Dict[str, Any]:
        """Create the initial state for the agent graph."""
        from langchain_core.messages import HumanMessage

        # 🔥 修复：创建包含任务描述的初始消息
        # 替代 pre_model_hook 的功能，让父图直接传入任务
        task_description = f"请对股票 {company_name} 进行全面分析，交易日期：{trade_date}"
        initial_message = HumanMessage(content=task_description)

        state = {
            "messages": [initial_message],
            "company_of_interest": company_name,
            "trade_date": str(trade_date),
            "task_id": task_id,
            "investment_debate_state": InvestDebateState(
                {
                    "history": "",
                    "current_response": "",
                    "count": 0,
                    # 修复：初始化完整的 InvestDebateState 字段
                    "current_round_index": 0,
                    "max_rounds": 2,  # 默认值，会被 ConditionalLogic 覆盖或使用
                    "rounds": [],
                    "bull_report_content": "",
                    "bear_report_content": "",
                    "bull_history": "",
                    "bear_history": "",
                    "judge_decision": ""
                }
            ),
            "risk_debate_state": RiskDebateState(
                {
                    "history": "",
                    "current_risky_response": "",
                    "current_safe_response": "",
                    "current_neutral_response": "",
                    "count": 0,
                    # 修复：初始化完整的 RiskDebateState 字段
                    "latest_speaker": "",
                    "risky_history": "",
                    "safe_history": "",
                    "neutral_history": "",
                    "judge_decision": "",
                    # 多轮辩论字段
                    "rounds": [],
                    "current_round_index": 0,
                    "max_rounds": 3,
                    "risky_report_content": "",
                    "safe_report_content": "",
                    "neutral_report_content": ""
                }
            ),
            # 报告字段和工具调用计数器由下方动态初始化逻辑根据配置文件生成
            "reports": {}, # 🔥 显式初始化 reports 字典
        }
        
        # 🔥 动态初始化前端配置的智能体报告字段
        try:
            from app.engine.agents.analysts.dynamic_analyst import DynamicAnalystFactory
            all_agents = DynamicAnalystFactory.get_all_agents()
            
            for agent in all_agents:
                slug = agent.get('slug', '')
                if not slug:
                    continue

                internal_key = slug.replace("-analyst", "").replace("-", "_")
                report_key = f"{internal_key}_report"

                if report_key not in state:
                    state[report_key] = ""
                    logger.debug(f"🔧 动态初始化报告字段: {report_key}")
                    
        except Exception as e:
            logger.warning(f"⚠️ 动态初始化智能体字段失败: {e}")
        
        return state

    def get_graph_args(self, use_progress_callback: bool = False) -> Dict[str, Any]:
        """Get arguments for the graph invocation.

        Args:
            use_progress_callback: If True, use 'updates' mode for node-level progress tracking.
                                  If False, use 'values' mode for complete state updates.
        """
        # 使用 'updates' 模式可以获取节点级别的更新，用于进度跟踪
        # 使用 'values' 模式可以获取完整的状态更新
        stream_mode = "updates" if use_progress_callback else "values"

        return {
            "stream_mode": stream_mode,
            "config": {"recursion_limit": self.max_recur_limit},
        }
