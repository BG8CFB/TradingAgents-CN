"""决策反思（自 graph/reflection.py 迁移，async 化并统一走 invoker 会话循环）"""

from typing import Any, Dict

from app.engine.orchestrator.invoker import run_agent_turn
from app.utils.logging_init import get_logger

logger = get_logger("engine.postprocess.reflector")

from app.engine.prompts.parts import REFLECTION_SYSTEM_PROMPT  # noqa: E402


class Reflector:
    """Handles reflection on decisions and updating memory."""

    def __init__(self, llm, task_id: str = "", user_id: str = ""):
        """Initialize the reflector with an LLM (task 上下文用于 token 用量归属)."""
        self.llm = llm
        self.task_id = task_id
        self.user_id = user_id
        self.reflection_system_prompt = REFLECTION_SYSTEM_PROMPT
        self._cached_situation = ""
        self._situation_hash = None

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

    async def _reflect_on_component(
        self, component_type: str, report: str, situation: str, returns_losses
    ) -> str:
        """Generate reflection for a component."""
        user_prompt = (
            f"Returns: {returns_losses}\n\nAnalysis/Decision: {report}\n\n"
            f"Objective Market Reports for Reference: {situation}"
        )

        try:
            return await run_agent_turn(
                self.llm, [], user_prompt,
                system=self.reflection_system_prompt,
                agent_key=f"reflection_{component_type}",
                phase="reflection",
                task_id=self.task_id,
                user_id=self.user_id,
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"反思组件 [{component_type}] 失败: {e}")
            return ""

    async def reflect_bull_researcher(self, current_state, returns_losses, bull_memory):
        """Reflect on bull researcher's analysis and update memory."""
        situation = self._get_situation(current_state)
        bull_debate_history = current_state.get("investment_debate_state", {}).get("bull_history", "")

        result = await self._reflect_on_component(
            "BULL", bull_debate_history, situation, returns_losses
        )
        if result:
            bull_memory.add_situations([(situation, result)])

    async def reflect_bear_researcher(self, current_state, returns_losses, bear_memory):
        """Reflect on bear researcher's analysis and update memory."""
        situation = self._get_situation(current_state)
        bear_debate_history = current_state.get("investment_debate_state", {}).get("bear_history", "")

        result = await self._reflect_on_component(
            "BEAR", bear_debate_history, situation, returns_losses
        )
        if result:
            bear_memory.add_situations([(situation, result)])

    async def reflect_trader(self, current_state, returns_losses, trader_memory):
        """Reflect on trader's decision and update memory."""
        situation = self._get_situation(current_state)
        trader_decision = current_state.get("trader_investment_plan", "")

        result = await self._reflect_on_component(
            "TRADER", trader_decision, situation, returns_losses
        )
        if result:
            trader_memory.add_situations([(situation, result)])

    async def reflect_invest_judge(self, current_state, returns_losses, invest_judge_memory):
        """Reflect on investment judge's decision and update memory."""
        situation = self._get_situation(current_state)
        judge_decision = current_state.get("investment_debate_state", {}).get("judge_decision", "")

        result = await self._reflect_on_component(
            "INVEST JUDGE", judge_decision, situation, returns_losses
        )
        if result:
            invest_judge_memory.add_situations([(situation, result)])

    async def reflect_risk_manager(self, current_state, returns_losses, risk_manager_memory):
        """Reflect on risk manager's decision and update memory."""
        situation = self._get_situation(current_state)
        judge_decision = current_state.get("risk_debate_state", {}).get("judge_decision", "")

        result = await self._reflect_on_component(
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
