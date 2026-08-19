"""
两级上下文压缩（对齐 claude-code services/compact/ 分层）

执行顺序：microcompact（本地清旧 tool_result）→ autocompact（LLM 总结）→ reactive compact（API 超窗兜底）

- 有效窗口 = context_window − min(max_output_tokens, 20000)（MAX_OUTPUT_TOKENS_FOR_SUMMARY）
- 触发阈值 = 有效窗口 − 分级 buffer（≥800k→50k / ≥400k→30k / 其余 13k）
- 预测式：本轮前估算 当前 + 最大输出 + 15k 工具结果增长，超有效窗口即提前压缩
- 熔断：连续 3 次压缩失败停止自动压缩（reactive 仍可单次兜底）
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple

from app.constants.llm_defaults import DEFAULT_CONTEXT_WINDOW, DEFAULT_MAX_TOKENS
from app.utils.logging_init import get_logger

from ..core.base import BaseLLMClient
from ..core.types import Message, Role, TextBlock, ToolResultBlock, ToolUseBlock
from .prompts import COMPACT_INSTRUCTIONS, COMPACT_SYSTEM_PROMPT, CONTINUATION_HEADER
from .token_counter import TokenCounter, estimate_messages_tokens

logger = get_logger("app.llm.compact")

# 占位符对齐 claude-code TIME_BASED_MC_CLEARED_MESSAGE
_OLD_RESULT_PLACEHOLDER = "[Old tool result content cleared]"

# 对齐 claude-code：摘要请求的输出上限（p99.99 摘要长度）
MAX_OUTPUT_TOKENS_FOR_SUMMARY = 20_000
# 预测式压缩：每轮工具结果增长预估（对齐 estimateMaxTurnGrowth 的 15k 增量项）
PREDICTED_TURN_GROWTH = 15_000
# 熔断阈值：连续失败次数
MAX_CONSECUTIVE_FAILURES = 3


def _tiered_buffer(context_window: int) -> int:
    """分级 buffer（对齐 claude-code autoCompact.ts）：≥800k→50k，≥400k→30k，否则 13k"""
    if context_window >= 800_000:
        return 50_000
    if context_window >= 400_000:
        return 30_000
    return 13_000


@dataclass
class CompactConfig:
    # 兜底默认（单一源头 app/constants/llm_defaults.py）；实际值由调用方
    # （agents.py 等）从 bundle/limits 解析后传入，禁止依赖小默认
    context_window: int = DEFAULT_CONTEXT_WINDOW  # 模型上下文窗口（输入侧）
    max_output_tokens: int = DEFAULT_MAX_TOKENS  # 单次输出上限（参与有效窗口扣减，封顶 20k）
    buffer: Optional[int] = None  # 缺省按窗口分级自动选择
    keep_recent_turns: int = 4  # microcompact 保留最近 N 轮
    min_tool_results_to_clear: int = 2  # 可清理的旧 tool_result 少于该数则直接走 LLM compact

    @property
    def effective_buffer(self) -> int:
        return self.buffer if self.buffer is not None else _tiered_buffer(self.context_window)

    @property
    def effective_window(self) -> int:
        """有效窗口 = context_window − min(max_output_tokens, 20000)"""
        return self.context_window - min(self.max_output_tokens, MAX_OUTPUT_TOKENS_FOR_SUMMARY)

    @property
    def threshold(self) -> int:
        """autocompact 触发阈值 = 有效窗口 − 分级 buffer"""
        return self.effective_window - self.effective_buffer


class AutoCompactor:
    """分层压缩器。runner 每轮调用 should_compact / compact；API 超窗时调用 reactive_compact。"""

    def __init__(
        self,
        client: BaseLLMClient,
        counter: TokenCounter,
        config: Optional[CompactConfig] = None,
    ):
        self.client = client
        self.counter = counter
        self.config = config or CompactConfig()
        self.consecutive_failures = 0  # 熔断计数
        self.reactive_attempted = False  # reactive 单次兜底标记（防死循环）

    # ── 触发判断 ──────────────────────────────────────────────

    def should_compact(self, messages: List[Message]) -> bool:
        """常规阈值判断（含熔断：连续失败后停止自动压缩）"""
        if self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            return False
        return self.counter.count(messages) >= self.config.threshold

    def should_compact_predictive(self, messages: List[Message]) -> bool:
        """预测式：当前 token + 本轮最大输出 + 工具结果增长预估 > 有效窗口 即提前压缩"""
        if self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            return False
        projected = self.counter.count(messages) + self.config.max_output_tokens + PREDICTED_TURN_GROWTH
        return projected > self.config.effective_window

    def is_blocking(self, messages: List[Message]) -> bool:
        """阻塞兜底（对齐 MANUAL_COMPACT_BUFFER）：接近硬上限时必须压缩"""
        return self.counter.count(messages) >= self.config.effective_window - 3_000

    # ── 压缩执行 ──────────────────────────────────────────────

    async def compact(self, messages: List[Message], system: Optional[str] = None) -> Tuple[List[Message], bool]:
        """执行压缩，返回 (新消息列表, 是否发生了 LLM 压缩)。

        顺序：先 microcompact（本地免费）；空间不足或仍超阈值 → LLM compact。
        连续 3 次 LLM 压缩失败后熔断（不再自动压缩，等待 reactive 兜底）。
        """
        token_before = self.counter.count(messages)
        new_messages = self._microcompact(messages)
        if new_messages is not messages:
            token_after = estimate_messages_tokens(new_messages)
            logger.info(
                f"🧹 [compact] microcompact: {token_before} -> {token_after} tokens (阈值 {self.config.threshold})"
            )
            if token_after < self.config.threshold:
                self.counter = TokenCounter()  # 估算重置，等待下轮 usage 校准
                return new_messages, False

        if self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            logger.warning("⚠️ [compact] 熔断中：跳过自动 LLM 压缩")
            return messages, False

        # LLM compact：历史整体替换为 [boundary(system标记), summary user message]
        try:
            summary = await self._summarize(messages, system)
        except Exception as e:  # noqa: BLE001 - 压缩失败不中断对话
            self.consecutive_failures += 1
            logger.warning(f"⚠️ [compact] LLM 压缩失败({self.consecutive_failures}/{MAX_CONSECUTIVE_FAILURES}): {e}")
            return messages, False
        self.consecutive_failures = 0

        compacted: List[Message] = []
        if system:
            compacted.append(Message(role=Role.SYSTEM, content=system))
        compacted.append(
            Message(
                role=Role.USER,
                content=CONTINUATION_HEADER + summary,
            )
        )
        logger.info(f"📦 [compact] LLM compact 完成: {token_before} tokens -> 摘要 {len(summary)} 字符")
        self.counter = TokenCounter()
        return compacted, True

    async def reactive_compact(self, messages: List[Message], system: Optional[str] = None) -> List[Message]:
        """reactive compact：API 真实返回 prompt-too-long 后的单次兜底（只试一次防死循环）"""
        if self.reactive_attempted:
            logger.warning("⚠️ [compact] reactive 已尝试过，不再重试")
            return messages
        self.reactive_attempted = True
        logger.warning("🔄 [compact] reactive compact：API 报告超窗，执行兜底压缩")
        new_messages, _ = await self.compact(messages, system)
        return new_messages

    # ── microcompact：清旧 tool_result ────────────────────────────

    def _microcompact(self, messages: List[Message]) -> List[Message]:
        """把最近 keep_recent_turns 轮之外的 tool_result 内容替换为占位符。无改动时原样返回。"""
        # 找到最近 N 轮边界（以 user 消息计轮）
        turn_boundary = len(messages)
        turns_seen = 0
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].role == Role.USER:
                turns_seen += 1
                if turns_seen > self.config.keep_recent_turns:
                    turn_boundary = i
                    break

        old_slice = messages[:turn_boundary]
        clearable = sum(1 for m in old_slice for b in m.blocks() if isinstance(b, ToolResultBlock))
        if clearable < self.config.min_tool_results_to_clear:
            return messages

        changed = False
        new_messages: List[Message] = []
        for i, m in enumerate(messages):
            if i < turn_boundary:
                blocks = []
                for b in m.blocks():
                    if isinstance(b, ToolResultBlock) and len(b.content) > len(_OLD_RESULT_PLACEHOLDER):
                        changed = True
                        blocks.append(
                            ToolResultBlock(
                                tool_use_id=b.tool_use_id,
                                content=_OLD_RESULT_PLACEHOLDER,
                                is_error=b.is_error,
                            )
                        )
                    else:
                        blocks.append(b)
                new_messages.append(Message(role=m.role, content=blocks))
            else:
                new_messages.append(m)
        return new_messages if changed else messages

    # ── LLM compact：无工具单轮总结 ────────────────────────────────

    async def _summarize(self, messages: List[Message], system: Optional[str]) -> str:
        """压缩请求本身就是一次普通 chat：全部历史 + 摘要指令，无工具、单轮"""
        request_messages = list(messages)
        request_messages.append(Message(role=Role.USER, content=TextBlock(text=COMPACT_INSTRUCTIONS)))
        resp = await self.client.chat(
            request_messages,
            system=system or COMPACT_SYSTEM_PROMPT,
            tools=None,
            max_tokens=self.config.max_output_tokens,
        )
        summary = resp.text()
        if not summary:
            logger.warning("⚠️ [compact] 压缩摘要为空，退化为 microcompact 后的历史")
            summary = "（摘要生成失败，以下为末尾对话保留）\n" + self._tail_text(messages, 2000)
        return summary

    @staticmethod
    def _tail_text(messages: List[Message], max_chars: int) -> str:
        parts: List[str] = []
        total = 0
        for m in reversed(messages):
            for b in reversed(m.blocks()):
                if isinstance(b, (TextBlock, ToolUseBlock)):
                    text = getattr(b, "text", "") or str(getattr(b, "input", ""))
                    parts.append(text[:300])
                    total += min(len(text), 300)
                    if total >= max_chars:
                        return "\n".join(reversed(parts))
        return "\n".join(reversed(parts))
