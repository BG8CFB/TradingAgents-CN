"""
执行状态注入器

参考 claw-code conversation.rs 中 run_turn 的设计：
- 每轮循环向 LLM 提供当前执行状态
- 让 LLM "知道" 自己已经做了什么、还能做多少
- 这是让 LLM 自主决定是否停止调用的关键

与 claw-code 的区别：claw-code 把状态放在 telemetry 层，我们把状态注入到消息中，
因为我们的 LLM 是通过消息列表交互的。
"""

from typing import Dict, List, Optional, Set

from langchain_core.messages import HumanMessage

from app.utils.logging_init import get_logger

logger = get_logger("executors.state_injector")


class StateInjector:
    """
    执行状态注入器

    使用方式:
        injector = StateInjector(max_iterations=12)
        # 每轮循环中：
        injector.record_tool_call("get_stock_data", args={"ticker": "000001"}, success=True)
        state_msg = injector.build_state_message(current_iteration=3)
        if state_msg:
            messages.append(state_msg)
    """

    def __init__(self, max_iterations: int = 12):
        self.max_iterations = max_iterations
        self._tool_history: List[Dict] = []
        self._tool_names_used: Set[str] = set()
        self._error_count: int = 0

    def record_tool_call(
        self,
        tool_name: str,
        args: Optional[Dict] = None,
        success: bool = True,
    ) -> None:
        """记录一次工具调用"""
        self._tool_history.append({
            "name": tool_name,
            "args": args or {},
            "success": success,
        })
        self._tool_names_used.add(tool_name)
        if not success:
            self._error_count += 1

    @property
    def total_tool_calls(self) -> int:
        return len(self._tool_history)

    @property
    def unique_tools_used(self) -> Set[str]:
        return set(self._tool_names_used)

    def build_state_message(
        self,
        current_iteration: int,
        inject_every: int = 3,
    ) -> Optional[HumanMessage]:
        """
        构建执行状态消息

        不是每轮都注入（避免浪费 token），而是每 N 轮注入一次。

        Args:
            current_iteration: 当前迭代次数（从 1 开始）
            inject_every: 每隔几轮注入一次（默认 3）

        Returns:
            HumanMessage 或 None（不需要注入时返回 None）
        """
        # 首轮、每 N 轮、或接近上限时注入
        should_inject = (
            current_iteration == 1
            or current_iteration % inject_every == 0
            or current_iteration >= self.max_iterations - 2
        )
        if not should_inject:
            return None

        remaining = max(0, self.max_iterations - current_iteration)

        # 构建已调用工具列表
        tool_summary_lines = []
        for record in self._tool_history:
            status = "✓" if record["success"] else "✗"
            tool_summary_lines.append(f"  {record['name']}({status})")

        tool_summary = "\n".join(tool_summary_lines) if tool_summary_lines else "  （尚未调用）"

        # 构建状态消息
        parts = [
            "📊 [执行状态 - 请仔细阅读]",
            f"当前迭代: {current_iteration}/{self.max_iterations}",
            f"已用工具调用: {self.total_tool_calls} 次",
            f"剩余可用调用: {remaining} 次",
            f"已使用工具:\n{tool_summary}",
        ]

        if self._error_count > 0:
            parts.append(f"⚠️ 工具失败次数: {self._error_count}")

        # 关键：给 LLM 明确的停止指导
        if remaining <= 2:
            parts.append(
                "🚨 剩余调用次数极少！请立即基于已有数据生成最终分析报告，不要再调用工具。"
            )
        elif remaining <= 4:
            parts.append(
                "⚠️ 剩余调用次数有限。如果已获取足够数据，请直接输出分析报告。"
            )
        else:
            parts.append(
                "💡 若已获取足够数据进行分析，请直接输出报告，无需继续调用工具。"
            )

        content = "\n".join(parts)
        return HumanMessage(content=content)

    def reset(self) -> None:
        """重置状态（新分析任务时调用）"""
        self._tool_history.clear()
        self._tool_names_used.clear()
        self._error_count = 0
