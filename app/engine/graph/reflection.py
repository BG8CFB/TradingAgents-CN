# TradingAgents/graph/reflection.py

from typing import Dict, Any
from langchain_openai import ChatOpenAI

# 导入统一日志系统
from app.utils.logging_init import get_logger
logger = get_logger("default")


class Reflector:
    """Handles reflection on decisions and updating memory."""

    def __init__(self, llm: ChatOpenAI):
        """Initialize the reflector with an LLM."""
        self.llm = llm
        self.reflection_system_prompt = self._get_reflection_prompt()
        self._cached_situation = ""
        self._situation_hash = None

    def _get_reflection_prompt(self) -> str:
        """Get the system prompt for reflection."""
        return """你是一位资深金融分析师，负责审查交易决策/分析并提供全面、循序渐进的深度分析。
你的目标是对投资决策提供详细洞察，并指出改进方向。请严格遵循以下准则：

1. 推理分析：
   - 对于每项交易决策，判断其是否正确。正确的决策应带来收益增长，错误的决策则相反。
   - 分析每个成功或失误的贡献因素，考虑：
     - 市场情报
     - 技术指标
     - 技术信号
     - 价格走势分析
     - 整体市场数据分析
     - 新闻分析
     - 社交媒体和情绪分析
     - 基本面数据分析
     - 评估各因素在决策过程中的重要性权重

2. 改进建议：
   - 对于任何错误决策，提出修正建议以最大化收益。
   - 提供详细的纠正措施或改进清单，包括具体建议（例如在特定日期将决策从"持有"改为"买入"）。

3. 总结：
   - 总结从成功和失误中获得的经验教训。
   - 说明如何将这些经验应用于未来的交易场景，并在相似情境之间建立联系以运用所学知识。

4. 提炼：
   - 从总结中提取关键洞察，凝练为不超过1000个字的精炼描述。
   - 确保提炼内容涵盖经验教训和推理过程的核心要点，便于后续参考。

请严格遵守以上指示，确保输出详细、准确且具有可操作性。你还将获得来自价格走势、技术指标、新闻和情绪等方面的客观市场描述，为分析提供更多上下文。"""

    def _extract_current_situation(self, current_state: Dict[str, Any]) -> str:
        """Extract the current market situation from the state."""
        # 🔥 动态发现所有 *_report 字段，自动支持新添加的分析师报告
        reports = []
        for key in current_state.keys():
            if key.endswith("_report"):
                content = current_state.get(key, "")
                if content:
                    reports.append(content)
        
        return "\n\n".join(reports)

    def _reflect_on_component(
        self, component_type: str, report: str, situation: str, returns_losses
    ) -> str:
        """Generate reflection for a component."""
        messages = [
            ("system", self.reflection_system_prompt),
            (
                "human",
                f"Returns: {returns_losses}\n\nAnalysis/Decision: {report}\n\nObjective Market Reports for Reference: {situation}",
            ),
        ]

        try:
            result = self.llm.invoke(messages).content
            return result
        except Exception as e:
            logger.error(f"反思组件 [{component_type}] 失败: {e}")
            return ""

    def reflect_bull_researcher(self, current_state, returns_losses, bull_memory):
        """Reflect on bull researcher's analysis and update memory."""
        situation = self._get_situation(current_state)
        bull_debate_history = current_state.get("investment_debate_state", {}).get("bull_history", "")

        result = self._reflect_on_component(
            "BULL", bull_debate_history, situation, returns_losses
        )
        if result:
            bull_memory.add_situations([(situation, result)])

    def reflect_bear_researcher(self, current_state, returns_losses, bear_memory):
        """Reflect on bear researcher's analysis and update memory."""
        situation = self._get_situation(current_state)
        bear_debate_history = current_state.get("investment_debate_state", {}).get("bear_history", "")

        result = self._reflect_on_component(
            "BEAR", bear_debate_history, situation, returns_losses
        )
        if result:
            bear_memory.add_situations([(situation, result)])

    def reflect_trader(self, current_state, returns_losses, trader_memory):
        """Reflect on trader's decision and update memory."""
        situation = self._get_situation(current_state)
        trader_decision = current_state.get("trader_investment_plan", "")

        result = self._reflect_on_component(
            "TRADER", trader_decision, situation, returns_losses
        )
        if result:
            trader_memory.add_situations([(situation, result)])

    def reflect_invest_judge(self, current_state, returns_losses, invest_judge_memory):
        """Reflect on investment judge's decision and update memory."""
        situation = self._get_situation(current_state)
        judge_decision = current_state.get("investment_debate_state", {}).get("judge_decision", "")

        result = self._reflect_on_component(
            "INVEST JUDGE", judge_decision, situation, returns_losses
        )
        if result:
            invest_judge_memory.add_situations([(situation, result)])

    def reflect_risk_manager(self, current_state, returns_losses, risk_manager_memory):
        """Reflect on risk manager's decision and update memory."""
        situation = self._get_situation(current_state)
        judge_decision = current_state.get("risk_debate_state", {}).get("judge_decision", "")

        result = self._reflect_on_component(
            "RISK JUDGE", judge_decision, situation, returns_losses
        )
        if result:
            risk_manager_memory.add_situations([(situation, result)])

    def _get_situation(self, current_state: Dict[str, Any]) -> str:
        """提取并缓存当前市场状况（基于内容哈希判断是否变化）"""
        report_keys = sorted(k for k in current_state if k.endswith("_report"))
        content_hash = hash(tuple(
            (k, current_state[k][:200] if isinstance(current_state.get(k), str) else "")
            for k in report_keys
        ))
        if not hasattr(self, '_cached_situation') or self._situation_hash != content_hash:
            self._cached_situation = self._extract_current_situation(current_state)
            self._situation_hash = content_hash
        return self._cached_situation
