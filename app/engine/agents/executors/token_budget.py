"""
Token 预算管理器

参考 claw-code 的 compact.rs / usage.rs：
- 估算消息列表的 token 占用（中文约 1.5 token/字，英文约 0.5 token/字）
- 当累积 token 超过阈值时，生成压缩建议
- 压缩策略：保留最近 N 条消息，旧消息总结为一条摘要消息
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.utils.logging_init import get_logger

logger = get_logger("executors.token_budget")

# 中文文本约 1.5 token/字，英文约 0.25 token/词，混合取 1.0 token/字符
CHARS_PER_TOKEN = 1.0

# 默认压缩阈值（token 数）
DEFAULT_COMPACT_THRESHOLD = 80000

# 默认保留最近几轮消息（一轮 = AI + Tool + AI + Tool ...）
DEFAULT_PRESERVE_ROUNDS = 4

# 摘要最大字符数
MAX_SUMMARY_CHARS = 2000


@dataclass
class BudgetStatus:
    """Token 预算状态"""
    estimated_tokens: int = 0
    threshold: int = DEFAULT_COMPACT_THRESHOLD
    needs_compact: bool = False
    message_count: int = 0
    tool_message_count: int = 0
    overhead_pct: float = 0.0

    def __str__(self) -> str:
        pct = (self.estimated_tokens / self.threshold * 100) if self.threshold else 0
        return (
            f"Token 预算: {self.estimated_tokens:,}/{self.threshold:,} ({pct:.0f}%), "
            f"消息数: {self.message_count}, 工具消息: {self.tool_message_count}"
        )


@dataclass
class CompactResult:
    """压缩结果"""
    original_count: int = 0
    compacted_count: int = 0
    removed_count: int = 0
    summary: str = ""
    was_compacted: bool = False


class TokenBudget:
    """
    Token 预算管理器

    使用方式:
        budget = TokenBudget(threshold=80000)
        status = budget.estimate(messages)
        if status.needs_compact:
            result = budget.compact(messages)
    """

    def __init__(
        self,
        threshold: int = DEFAULT_COMPACT_THRESHOLD,
        preserve_rounds: int = DEFAULT_PRESERVE_ROUNDS,
    ):
        self.threshold = threshold
        self.preserve_rounds = preserve_rounds

    def estimate(self, messages: List[BaseMessage]) -> BudgetStatus:
        """估算消息列表的 token 占用"""
        total_chars = 0
        tool_count = 0

        for msg in messages:
            content = self._extract_text(msg)
            total_chars += len(content)
            if isinstance(msg, ToolMessage):
                tool_count += 1

        estimated = int(total_chars * CHARS_PER_TOKEN)
        overhead_pct = (estimated / self.threshold * 100) if self.threshold else 0

        return BudgetStatus(
            estimated_tokens=estimated,
            threshold=self.threshold,
            needs_compact=estimated >= self.threshold,
            message_count=len(messages),
            tool_message_count=tool_count,
            overhead_pct=overhead_pct,
        )

    def should_compact(self, messages: List[BaseMessage]) -> bool:
        """检查是否需要压缩"""
        return self.estimate(messages).needs_compact

    def compact(self, messages: List[BaseMessage]) -> Tuple[List[BaseMessage], CompactResult]:
        """
        压缩消息列表

        策略：
        1. 保留第一条 SystemMessage（如果有）
        2. 保留最近 N 轮消息（一轮 = AI 响应 + 所有 ToolMessage + 下一个 AI 响应）
        3. 将中间的旧消息压缩为一条摘要 HumanMessage

        Returns:
            (压缩后的消息列表, CompactResult)
        """
        if not messages:
            return messages, CompactResult()

        status = self.estimate(messages)
        if not status.needs_compact:
            return messages, CompactResult(
                original_count=len(messages),
                compacted_count=len(messages),
            )

        # 1. 分离 SystemMessage
        system_msgs: List[BaseMessage] = []
        rest_msgs: List[BaseMessage] = []
        for msg in messages:
            if isinstance(msg, SystemMessage) and not system_msgs:
                system_msgs.append(msg)
            else:
                rest_msgs.append(msg)

        # 2. 找到保留的起始位置（从后往前数 preserve_rounds 轮）
        preserve_start = self._find_preserve_boundary(rest_msgs)

        # 3. 压缩旧消息
        old_msgs = rest_msgs[:preserve_start]
        recent_msgs = rest_msgs[preserve_start:]

        if not old_msgs:
            return messages, CompactResult(
                original_count=len(messages),
                compacted_count=len(messages),
            )

        summary = self._generate_summary(old_msgs)
        summary_msg = HumanMessage(
            content=f"[历史分析摘要]\n{summary}\n\n--- 以上为之前分析的压缩摘要，请基于此和后续新数据继续分析 ---"
        )

        result = system_msgs + [summary_msg] + recent_msgs

        logger.info(
            f"📦 [TokenBudget] 上下文压缩: {len(messages)} → {len(result)} 条消息, "
            f"移除 {len(old_msgs)} 条旧消息"
        )

        return result, CompactResult(
            original_count=len(messages),
            compacted_count=len(result),
            removed_count=len(old_msgs),
            summary=summary,
            was_compacted=True,
        )

    def _extract_text(self, msg: BaseMessage) -> str:
        """从消息中提取文本内容"""
        content = getattr(msg, "content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    parts.append(item.get("text", ""))
            return " ".join(parts)
        return str(content) if content else ""

    def _find_preserve_boundary(self, messages: List[BaseMessage]) -> int:
        """
        从后往前找到保留的起始位置

        一轮定义为：一个 AIMessage（含 tool_calls）→ 连续的 ToolMessage → 下一个 AIMessage
        如果没有 tool_calls 的 AIMessage，按消息数量估算。
        """
        if not messages:
            return 0

        rounds_found = 0
        i = len(messages) - 1

        while i >= 0 and rounds_found < self.preserve_rounds:
            msg = messages[i]
            if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                rounds_found += 1
            elif isinstance(msg, HumanMessage):
                rounds_found += 1
            elif isinstance(msg, AIMessage):
                rounds_found += 1
            elif isinstance(msg, ToolMessage):
                if i + 1 < len(messages) and not isinstance(messages[i + 1], ToolMessage):
                    rounds_found += 1
            i -= 1

        if rounds_found > 0:
            return max(0, i + 1)

        # 回退：至少保留最后 1 条，压缩前面所有内容
        return max(0, len(messages) - 1)

        return max(0, i + 1)

    def _generate_summary(self, old_msgs: List[BaseMessage]) -> str:
        """从旧消息中提取关键信息生成摘要"""
        tool_summaries: List[str] = []
        ai_summaries: List[str] = []

        for msg in old_msgs:
            text = self._extract_text(msg)
            if isinstance(msg, ToolMessage):
                name = getattr(msg, "name", "unknown")
                truncated = text[:200] + "..." if len(text) > 200 else text
                tool_summaries.append(f"- 工具 {name}: {truncated}")
            elif isinstance(msg, AIMessage):
                content = text[:300] + "..." if len(text) > 300 else text
                if content.strip():
                    ai_summaries.append(content)

        parts = []
        if ai_summaries:
            parts.append("=== AI 分析内容 ===")
            parts.extend(ai_summaries[-3:])  # 只保留最后 3 条 AI 分析
        if tool_summaries:
            parts.append("\n=== 工具调用结果 ===")
            parts.extend(tool_summaries[-10:])  # 只保留最后 10 条工具结果

        summary = "\n".join(parts)
        if len(summary) > MAX_SUMMARY_CHARS:
            summary = summary[:MAX_SUMMARY_CHARS] + "\n...[摘要已截断]"
        return summary
