"""决策反思（自 graph/reflection.py 迁移，async 化并统一走 invoker 会话循环）。

P4-b 声明式输入适配：反思入口不再按内置 5 槽各写一个读死键的方法，
由编译计划的记忆反思声明（plan.MemoryReflection，经执行计划快照透传）
驱动——单条声明 = 「一个记忆槽 + 该节点自己的历史产出」，自定义工作流
（任意 N 方辩论组/任意裁决节点）与内置工作流走同一路径。反思输入文本
的派生见 runtime._reflection_input。
"""

from typing import Any, Dict

from app.engine.orchestrator.invoker import run_agent_turn
import logging

logger = logging.getLogger("engine.postprocess.reflector")

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

    async def reflect_component(
        self,
        component_key: str,
        report: str,
        current_state: Dict[str, Any],
        returns_losses,
        memory,
    ) -> bool:
        """单条记忆绑定的反思：节点历史产出 → 经验 → 写入记忆库。

        Args:
            component_key: 反思对象标识（token 归属 agent_key；内置节点保持
                旧专用方法口径 BULL/BEAR/TRADER/INVEST JUDGE/RISK JUDGE，自定义 = slug）
            report: 该节点的累积历史产出（发言史/裁决/报告；空则跳过）
            current_state: 任务最终 state（用于提取市场情景）
            returns_losses: 回测区间收益（回测方组装）
            memory: 记忆库实例（None 跳过）

        Returns:
            是否写入了记忆（ False = 输入为空/反思失败/记忆缺失）
        """
        if not report or memory is None:
            return False
        situation = self._get_situation(current_state)

        user_prompt = (
            f"Returns: {returns_losses}\n\nAnalysis/Decision: {report}\n\n"
            f"Objective Market Reports for Reference: {situation}"
        )

        try:
            result = await run_agent_turn(
                self.llm,
                [],
                user_prompt,
                system=self.reflection_system_prompt,
                agent_key=f"reflection_{component_key}",
                phase="reflection",
                task_id=self.task_id,
                user_id=self.user_id,
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"反思组件 [{component_key}] 失败: {e}")
            return False

        if result:
            memory.add_situations([(situation, result)])
            return True
        return False

    def _get_situation(self, current_state: Dict[str, Any]) -> str:
        """提取并缓存当前市场状况（基于内容哈希判断是否变化）"""
        report_keys = sorted(k for k in current_state if k.endswith("_report"))
        content_hash = hash(
            tuple((k, current_state[k][:200] if isinstance(current_state.get(k), str) else "") for k in report_keys)
        )
        if not hasattr(self, "_cached_situation") or self._situation_hash != content_hash:
            self._cached_situation = self._extract_current_situation(current_state)
            self._situation_hash = content_hash
        return self._cached_situation
