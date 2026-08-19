"""
agent 循环（对齐 claude-code query.ts 的核心模式）

核心约定：
- 唯一退出信号：响应中没有 ToolUseBlock → 自然停止（StopReason.END_TURN）
- max_turns 安全兜底；max_output_tokens 截断恢复（升级重发 + 恢复消息，上限 3 次）
- 每轮发送前分层压缩检查：预测式 / 阈值 / 阻塞兜底（compact/auto_compactor.py）
- API 调用经 with_retry（10 次指数退避，限流 3 次触发 fallback）
- 工具结果之后、下次调用之前：drain 用户消息队列（system-reminder 包装注入）
- 同轮多工具按"并发安全分区"执行（orchestration/concurrency.py）
- 可选事件流（events.py）：每轮 LLM 调用 / 工具调用 / 压缩 / 用户消息注入发事件
"""

import inspect
import time
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

from app.utils.logging_init import get_logger

from .compact.auto_compactor import AutoCompactor, CompactConfig
from .compact.token_counter import TokenCounter
from .core.base import BaseLLMClient
from .core.errors import ContextWindowExceededError
from .core.types import ChatResponse, Message, Role, ToolResultBlock, ToolUseBlock
from .orchestration.concurrency import partition_tool_calls, run_batches
from .retry import DEFAULT_MAX_RETRIES, FallbackTriggeredError, with_retry

logger = get_logger("app.llm.runner")

DEFAULT_MAX_TURNS = 16
ESCALATED_MAX_TOKENS = 64_000  # 截断恢复：升级输出上限（对齐 claude-code）
MAX_OUTPUT_TOKENS_RECOVERY_LIMIT = 3  # 恢复消息注入次数上限
RECOVERY_INSTRUCTION = (
    "Output token limit hit. Resume directly from where you stopped — no apology, "
    "no repetition, continue the unfinished content."
)


@dataclass
class RunResult:
    """一次完整对话的结果"""

    messages: List[Message] = field(default_factory=list)  # 完整历史（含压缩后替换）
    final_text: str = ""
    turns: int = 0
    tool_calls_executed: int = 0
    total_tokens: int = 0  # 各轮 input+output 累加（含压缩请求）
    compacted: bool = False
    stop_reason: str = ""
    user_messages_injected: int = 0


async def run_conversation(
    client: BaseLLMClient,
    user_message: str,
    *,
    system: Optional[str] = None,
    tools: Optional[List[Any]] = None,
    registry: Optional[Any] = None,
    max_turns: int = DEFAULT_MAX_TURNS,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    fallback_client: Optional[BaseLLMClient] = None,
    retry_times: Optional[int] = None,
    history: Optional[List[Message]] = None,
    on_text_delta: Optional[Callable[[str], None]] = None,
    compact_config: Optional[CompactConfig] = None,
    enable_skill_listing: bool = False,
    skill_dirs: Optional[List[str]] = None,
    task_id: str = "",
    agent_key: str = "",
    phase: str = "",
    event_sink: Optional[Any] = None,
    inbox: Optional[Any] = None,
) -> RunResult:
    """跑一轮完整对话（含工具调用、自动压缩、用户消息注入与事件流）。

    Args:
        client: 协议客户端（anthropic / openai）
        user_message: 本轮用户输入
        system: 系统提示词
        tools: ToolDef 列表（缺省用 registry.defs()）
        registry: ToolRegistry（执行工具用；tools 与 registry 二者至少给一个）
        history: 已有历史（多轮对话时传入，会原地延续）
        on_text_delta: 流式文本回调（可选）
        enable_skill_listing: 注入 skill 清单（渐进式披露，需 registry 中有 `skill` 工具）
        skill_dirs: skill 扫描目录（缺省 config/skills/）
        task_id / agent_key / phase / event_sink: 事件流标识与汇聚点（events.py）
        inbox: AgentMessageInbox（message_queue.py）——运行中接收用户消息
        fallback_client: 限流 fallback 客户端（连续 3 次 429 触发切换，对齐
            claude-code query.ts：清本轮消息后用备模型重放整个请求；仅切换一次）
        retry_times: 覆盖默认重试上限（数据库每模型配置 retry_times）
    """
    from .tools.registry import ToolRegistry, tool_registry as default_registry

    reg: ToolRegistry = registry or default_registry
    tool_defs = tools if tools is not None else reg.defs()

    # ad-hoc 工具（tools 传入但未注册进 registry）：执行时直接调 handler
    extra_defs = {t.name: t for t in tool_defs if reg.get(t.name) is None}

    async def emit(event_type: str, **payload: Any) -> None:
        if event_sink is not None:
            await event_sink.emit(event_type, agent_key=agent_key, phase=phase, **payload)

    messages = history if history is not None else []
    messages.append(Message(role=Role.USER, content=user_message))

    # skill 清单（渐进式披露）：仅注入 name+description，命中后模型经 skill 工具取全文
    if enable_skill_listing:
        listing = _build_skill_listing(skill_dirs)
        if listing:
            system = (system + "\n\n" if system else "") + listing

    counter = TokenCounter()
    compactor = AutoCompactor(client, counter, compact_config)

    result = RunResult(messages=messages)
    turns = 0
    output_recovery_count = 0  # 截断恢复计数
    escalated_max_tokens: Optional[int] = None  # 截断恢复时升级的输出上限
    reacted_too_long = False  # reactive compact 已触发标记
    active_client = client  # 限流 fallback 时切换（仅一次）
    used_fallback = False

    # 并发安全查找表：tool 名 → is_concurrency_safe
    safe_map = {t.name: bool(t.is_concurrency_safe) for t in tool_defs}

    while True:
        turns += 1
        if turns > max_turns:
            logger.warning(f"⚠️ [runner] 达到最大轮数 {max_turns}，强制停止")
            result.stop_reason = "max_turns"
            break

        # 发送前分层压缩检查（预测式 / 常规阈值 / 阻塞兜底）
        need_compact = (
            compactor.should_compact(messages)
            or compactor.should_compact_predictive(messages)
            or compactor.is_blocking(messages)
        )
        if need_compact:
            messages, llm_compacted = await compactor.compact(messages, system=system)
            if llm_compacted:
                result.compacted = True
                await emit("compact", level="auto", messages=len(messages))

        # ── 调用模型（流式；带重试；聚合文本增量）────────────────────
        await emit(
            "llm_request",
            messages=len(messages),
            tools=len(tool_defs),
            estimated_tokens=counter.count(messages),
        )

        async def _call() -> ChatResponse:
            resp_local: Optional[ChatResponse] = None
            async for event in active_client.chat_stream(
                messages,
                system=system,
                tools=tool_defs or None,
                max_tokens=escalated_max_tokens or max_tokens,
                temperature=temperature,
            ):
                if event.type == "text_delta":
                    if on_text_delta:
                        on_text_delta(event.text)
                    await emit("text_delta", text=event.text)
                elif event.type == "message" and event.response:
                    resp_local = event.response
            if resp_local is None:
                raise RuntimeError("未收到完整响应（流中断）")
            return resp_local

        try:
            resp = await with_retry(_call, max_retries=retry_times if retry_times is not None else DEFAULT_MAX_RETRIES)
        except FallbackTriggeredError:
            # 限流连续触发（对齐 claude-code query.ts）：本轮响应尚未入历史，
            # 切换备模型直接重放整个请求；无备模型或已切换过则上抛
            if fallback_client is not None and not used_fallback:
                used_fallback = True
                active_client = fallback_client
                logger.warning(
                    f"⚠️ [runner] 连续限流，切换 fallback 模型 → {getattr(fallback_client, 'model', '')} 重放本轮"
                )
                await emit("model_fallback", model=getattr(fallback_client, "model", ""))
                continue
            raise
        except ContextWindowExceededError:
            if not reacted_too_long:
                # reactive compact：API 真实超窗 → 单次兜底压缩后重试本轮
                reacted_too_long = True
                messages = await compactor.reactive_compact(messages, system)
                result.compacted = True
                await emit("compact", level="reactive", messages=len(messages))
                continue
            result.stop_reason = "context_window_exceeded"
            logger.error("❌ [runner] reactive compact 后仍超窗，停止")
            break

        messages.append(resp.message)
        result.total_tokens += resp.usage.total
        await emit(
            "llm_response",
            stop_reason=resp.stop_reason.value,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
        )

        # usage 校准 token 计数
        counter.update_from_usage(resp.usage.input_tokens, len(messages))

        # ── max_output_tokens 截断恢复（对齐 claude-code 两级恢复）──
        if resp.stop_reason.value == "max_tokens":
            if escalated_max_tokens is None and (max_tokens or 0) and (max_tokens or 0) <= 8_192:
                escalated_max_tokens = ESCALATED_MAX_TOKENS  # ① 升级输出上限重发
                logger.warning(f"⚠️ [runner] 输出截断，升级 max_tokens → {ESCALATED_MAX_TOKENS} 重发")
                messages.pop()  # 本轮截断响应不保留
                continue
            if output_recovery_count < MAX_OUTPUT_TOKENS_RECOVERY_LIMIT:
                output_recovery_count += 1  # ② 注入恢复消息续写
                logger.warning(
                    f"⚠️ [runner] 输出截断，注入恢复消息 ({output_recovery_count}/{MAX_OUTPUT_TOKENS_RECOVERY_LIMIT})"
                )
                messages.append(Message(role=Role.USER, content=RECOVERY_INSTRUCTION))
                continue
            logger.error("❌ [runner] 截断恢复耗尽，保留截断结果继续")
            result.final_text = resp.text()
            result.stop_reason = resp.stop_reason.value
            break

        tool_uses = resp.tool_uses()
        if not tool_uses:
            # 模型准备结束：先检查是否有用户在最后流式输出期间发来的消息。
            # 有则注入并续轮（对齐 claude-code：排队消息必须在当前任务后处理），
            # 避免消息在 end_turn 边界被静默丢弃。
            if inbox is not None:
                injected = await inbox.drain_async()
                if injected:
                    for msg in injected:
                        messages.append(msg)
                        result.user_messages_injected += 1
                        await emit("user_message_injected", text=msg.content[:200])
                    continue
            result.final_text = resp.text()
            result.stop_reason = resp.stop_reason.value
            break

        # ── 同轮多工具：并发分区执行 ─────────────────────────────────
        outputs = await _execute_partitioned(reg, tool_uses, safe_map, extra_defs, emit)
        result.tool_calls_executed += len(tool_uses)
        result_blocks = [
            ToolResultBlock(
                tool_use_id=tu.id,
                content=out,
                is_error=out.startswith("错误") or out.startswith("工具执行失败"),
            )
            for tu, out in zip(tool_uses, outputs)
        ]
        messages.append(Message(role=Role.USER, content=result_blocks))

        # ── 用户消息注入（对齐 queued_command attachment：工具结果后、下次调用前）──
        if inbox is not None:
            injected = await inbox.drain_async()
            for msg in injected:
                messages.append(msg)
                result.user_messages_injected += 1
                await emit("user_message_injected", text=msg.content[:200])

    result.turns = min(turns, max_turns)
    return result


async def _execute_partitioned(
    reg,
    tool_uses: List[ToolUseBlock],
    safe_map: dict,
    extra_defs: Optional[dict] = None,
    emit: Optional[Any] = None,
) -> List[str]:
    """按并发分区执行同轮工具调用；未注册进 registry 的 ad-hoc 工具直接调 handler"""

    async def _exec(tu: ToolUseBlock) -> str:
        logger.info(f"🔧 [runner] 工具调用: {tu.name}({tu.input})")
        start = time.time()
        if emit is not None:
            await emit("tool_call", tool=tu.name, input=tu.input)
        try:
            if extra_defs and tu.name in extra_defs:
                result = extra_defs[tu.name].handler(**tu.input)
                if inspect.isawaitable(result):
                    result = await result
                out = str(result)
            else:
                out = await reg.execute(tu.name, tu.input)
        except Exception as e:  # noqa: BLE001 - 回传错误而非中断
            out = f"工具执行失败: {e}"
        if emit is not None:
            await emit(
                "tool_result",
                tool=tu.name,
                output=out[:2000],
                duration_ms=int((time.time() - start) * 1000),
                is_error=out.startswith("错误") or out.startswith("工具执行失败"),
            )
        return out

    batches = partition_tool_calls(tool_uses, lambda name: safe_map.get(name, False))
    return await run_batches(batches, _exec)


def _build_skill_listing(skill_dirs: Optional[List[str]]) -> str:
    """生成 skill 清单文本（渐进式披露）；无可用 skill 时返回空串"""
    try:
        from .skills.loader import SkillStore

        store = SkillStore(skill_dirs)
        return store.listing_text()
    except Exception as e:  # noqa: BLE001 - 清单失败不阻断对话
        logger.warning(f"⚠️ [runner] skill 清单生成失败: {e}")
        return ""
