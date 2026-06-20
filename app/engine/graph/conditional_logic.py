# TradingAgents/graph/conditional_logic.py
"""
条件逻辑模块 - 处理 LangGraph 工作流中的条件判断

只处理阶段2-4的条件判断，阶段1已重构为简单模式。
"""

from app.engine.agents.utils.agent_states import AgentState

# 导入统一日志系统
from app.utils.logging_init import get_logger
logger = get_logger("default")

# 硬编码安全上限，防止配置错误导致无限循环
MAX_ROUNDS = 10


class ConditionalLogic:
    """Handles conditional logic for determining graph flow."""

    def __init__(self, max_debate_rounds=1, max_risk_discuss_rounds=1):
        """Initialize with configuration parameters."""
        self.max_debate_rounds = min(max_debate_rounds, MAX_ROUNDS)
        self.max_risk_discuss_rounds = min(max_risk_discuss_rounds, MAX_ROUNDS)
        if max_debate_rounds > MAX_ROUNDS:
            logger.warning(
                f"⚠️ [ConditionalLogic] max_debate_rounds={max_debate_rounds} 超过安全上限 "
                f"{MAX_ROUNDS}，已自动裁减"
            )
        if max_risk_discuss_rounds > MAX_ROUNDS:
            logger.warning(
                f"⚠️ [ConditionalLogic] max_risk_discuss_rounds={max_risk_discuss_rounds} "
                f"超过安全上限 {MAX_ROUNDS}，已自动裁减"
            )

    # ========== 2阶段：投资辩论 ==========

    def should_continue_debate(self, state: AgentState) -> str:
        """Determine if debate should continue."""
        debate_state = state.get("investment_debate_state") or {}
        current_count = debate_state.get("count", 0)
        max_count = 2 * (self.max_debate_rounds + 1)
        latest_speaker = debate_state.get("latest_speaker", "")

        # 🔍 详细日志
        logger.info(f"🔍 [投资辩论控制] 当前发言次数: {current_count}, 最大次数: {max_count} (配置轮次: {self.max_debate_rounds})")
        logger.info(f"🔍 [投资辩论控制] 最后发言者: {latest_speaker}")

        if current_count >= max_count:
            logger.info("✅ [投资辩论控制] 达到最大次数，结束辩论 -> Research Manager")
            return "Research Manager"

        # 使用结构化 latest_speaker 字段路由
        if "Bull" in latest_speaker or "多头" in latest_speaker:
            next_speaker = "Bear Researcher"
        elif "Bear" in latest_speaker or "空头" in latest_speaker:
            next_speaker = "Bull Researcher"
        else:
            # 兜底：如果无法识别，根据 count 奇偶交替
            next_speaker = "Bull Researcher" if current_count % 2 == 0 else "Bear Researcher"
            logger.warning(f"⚠️ [投资辩论控制] 无法识别发言者身份: {latest_speaker[:20]}...，默认跳转 -> {next_speaker}")

        logger.info(f"🔄 [投资辩论控制] 继续辩论 -> {next_speaker}")
        return next_speaker

    # ========== 3阶段：风险讨论 ==========

    def should_continue_risk_analysis(self, state: AgentState) -> str:
        """Determine if risk analysis should continue."""
        risk_state = state.get("risk_debate_state") or {}
        current_count = risk_state.get("count", 0)
        max_count = 3 * (self.max_risk_discuss_rounds + 1)
        latest_speaker = risk_state.get("latest_speaker", "")
        if not latest_speaker:
            if current_count >= max_count:
                logger.info("✅ [风险讨论控制] latest_speaker 为空但已达上限 -> Risk Judge")
                return "Risk Judge"
            logger.warning("⚠️ [风险讨论控制] latest_speaker 为空，默认继续 -> Risky Analyst")
            return "Risky Analyst"

        # 🔍 详细日志
        logger.info(f"🔍 [风险讨论控制] 当前发言次数: {current_count}, 最大次数: {max_count} (配置轮次: {self.max_risk_discuss_rounds})")
        logger.info(f"🔍 [风险讨论控制] 最后发言者: {latest_speaker}")

        if current_count >= max_count:
            logger.info("✅ [风险讨论控制] 达到最大次数，结束讨论 -> Risk Judge")
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
