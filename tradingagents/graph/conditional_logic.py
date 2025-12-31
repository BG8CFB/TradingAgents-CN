# TradingAgents/graph/conditional_logic.py
"""
条件逻辑模块 - 处理 LangGraph 工作流中的条件判断

只处理阶段2-4的条件判断，阶段1已重构为简单模式。
"""

from tradingagents.agents.utils.agent_states import AgentState

# 导入统一日志系统
from tradingagents.utils.logging_init import get_logger
logger = get_logger("default")


class ConditionalLogic:
    """Handles conditional logic for determining graph flow."""

    def __init__(self, max_debate_rounds=1, max_risk_discuss_rounds=1):
        """Initialize with configuration parameters."""
        self.max_debate_rounds = max_debate_rounds
        self.max_risk_discuss_rounds = max_risk_discuss_rounds

    # ========== 2阶段：投资辩论 ==========

    def should_continue_debate(self, state: AgentState) -> str:
        """Determine if debate should continue."""
        current_count = state["investment_debate_state"]["count"]
        max_count = 2 * (self.max_debate_rounds + 1)
        latest_speaker = state["investment_debate_state"]["current_response"]

        # 🔍 详细日志
        logger.info(f"🔍 [投资辩论控制] 当前发言次数: {current_count}, 最大次数: {max_count} (配置轮次: {self.max_debate_rounds})")
        logger.info(f"🔍 [投资辩论控制] 最后发言者: {latest_speaker}")

        if current_count >= max_count:
            logger.info(f"✅ [投资辩论控制] 达到最大次数，结束辩论 -> Research Manager")
            return "Research Manager"

        # 兼容英文 "Bull" 和中文 "【多头"
        is_bull = current_speaker.startswith("Bull") or "【多头" in latest_speaker

        # 兼容英文 "Bear" 和中文 "【空头" (防御性编程：显式检查)
        is_bear = current_speaker.startswith("Bear") or "【空头" in latest_speaker

        if is_bull:
            next_speaker = "Bear Researcher"
        elif is_bear:
            next_speaker = "Bull Researcher"
        else:
            # 默认回落逻辑：如果无法识别，交替进行
            # 假设如果上一轮不是 Bull，那下一轮就该 Bull 了（或者反之，取决于设计）
            # 这里保持原有的 else 逻辑作为兜底
            next_speaker = "Bull Researcher"
            logger.warning(f"⚠️ [投资辩论控制] 无法识别发言者身份: {latest_speaker[:20]}...，默认跳转 -> {next_speaker}")

        logger.info(f"🔄 [投资辩论控制] 继续辩论 -> {next_speaker}")
        return next_speaker

    # ========== 3阶段：风险讨论 ==========

    def should_continue_risk_analysis(self, state: AgentState) -> str:
        """Determine if risk analysis should continue."""
        current_count = state["risk_debate_state"]["count"]
        max_count = 3 * self.max_risk_discuss_rounds
        latest_speaker = state["risk_debate_state"]["latest_speaker"]

        # 🔍 详细日志
        logger.info(f"🔍 [风险讨论控制] 当前发言次数: {current_count}, 最大次数: {max_count} (配置轮次: {self.max_risk_discuss_rounds})")
        logger.info(f"🔍 [风险讨论控制] 最后发言者: {latest_speaker}")

        if current_count >= max_count:
            logger.info(f"✅ [风险讨论控制] 达到最大次数，结束讨论 -> Risk Judge")
            return "Risk Judge"

        # 确定下一个发言者
        if latest_speaker.startswith("Risky"):
            next_speaker = "Safe Analyst"
        elif latest_speaker.startswith("Safe"):
            next_speaker = "Neutral Analyst"
        else:
            next_speaker = "Risky Analyst"

        logger.info(f"🔄 [风险讨论控制] 继续讨论 -> {next_speaker}")
        return next_speaker

    # ========== 动态方法处理 ==========
    # 🔥 [已废弃] 阶段1已重构为简单模式，不再需要动态条件判断方法 ==========
