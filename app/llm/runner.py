"""
agent 循环（对齐 claude-code query.ts 的核心模式）

核心约定：
- 唯一退出信号：响应中没有 ToolUseBlock → 自然停止（StopReason.END_TURN）
- max_turns 安全兜底；max_output_tokens 截断恢复（升级重发 + 恢复消息，上限 3 次）
- 每轮发送前分层压缩检查：预测式 / 阈值 / 阻塞兜底（compact/auto_compactor.py）
- API 调用经 with_retry（10 次指数退避，限流 3 次触发 fallback）
- 工具结果之后、下次调用之前：drain 用户消息队列（system-reminder 包装注入）
- 同轮多工具按"并发安全分区"执行（orchestration/concurrency.py）
- 可选事件流（events.py）：每轮 LLM 调用 / 工具调用 / 压缩 / 用户消息注入发事件；
  thinking 增量（thinking_delta）实时转发，聚合 thinking 事件先于 llm_response 发射
  （思考在生成顺序上先于正文，seq 决定时间线与回放呈现顺序）
"""

import inspect
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import logging

from .compact.auto_compactor import AutoCompactor, CompactConfig
from .compact.token_counter import TokenCounter
from .core.base import BaseLLMClient
from .core.errors import ContextWindowExceededError
from .core.types import ChatResponse, Message, Role, ToolResultBlock, ToolUseBlock
from .limits import resolve_output_limits
from .orchestration.concurrency import partition_tool_calls, run_batches
from .events import (
    TOOL_RESULT_MAX_CHARS,
    messages_event_payload,
    unwrap_system_reminder,
)
from .retry import DEFAULT_MAX_RETRIES, FallbackTriggeredError, with_retry

logger = logging.getLogger("app.llm.runner")

DEFAULT_MAX_TURNS = 16
MAX_OUTPUT_TOKENS_RECOVERY_LIMIT = 3  # 恢复消息注入次数上限
RECOVERY_INSTRUCTION = (
    "Output token limit hit. Resume directly from where you stopped — no apology, "
    "no repetition, continue the unfinished content."
)


def _extract_thinking_text(resp: ChatResponse) -> str:
    """防御式抽取 thinking/reasoning 块文本。

    canonical 层（core.types）目前不保留 thinking 块，此处从原始 SDK 响应提取：
    - Anthropic: raw.content 中 type 为 thinking/reasoning 的块（.thinking/.text）
    - OpenAI 兼容: raw.choices[0].message.reasoning_content / reasoning
    抽取全程异常安全，失败返回空串（不发射 thinking 事件）。
    """
    parts: List[str] = []
    try:
        raw = getattr(resp, "raw", None)
        content = getattr(raw, "content", None)
        if isinstance(content, list):
            for b in content:
                if getattr(b, "type", "") in ("thinking", "reasoning"):
                    t = getattr(b, "thinking", None) or getattr(b, "text", None) or getattr(b, "reasoning", None)
                    if t:
                        parts.append(str(t))
        if not parts:
            choices = getattr(raw, "choices", None)
            if choices:
                msg = getattr(choices[0], "message", None)
                if msg is not None:
                    t = getattr(msg, "reasoning_content", None) or getattr(msg, "reasoning", None)
                    if t:
                        parts.append(str(t))
    except Exception as e:  # noqa: BLE001 - thinking 抽取失败不影响主流程
        logger.debug(f"[runner] thinking 块抽取失败: {e}")
    return "\n".join(parts)


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
    thinking_budget: Optional[int] = None,
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
    user_id: str = "",
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
        user_id: 任务发起者（token 用量统计归属，由调用侧从 state 透传）
        inbox: AgentMessageInbox（message_queue.py）——运行中接收用户消息
        fallback_client: 限流 fallback 客户端（连续 3 次 429 触发切换，对齐
            claude-code query.ts：清本轮消息后用备模型重放整个请求；仅切换一次）
        retry_times: 覆盖默认重试上限（数据库每模型配置 retry_times）
        thinking_budget: 推理思考预算（Anthropic extended thinking opt-in 开关，
            >0 时启用；OpenAI 协议侧忽略——vllm/Qwen 系默认输出 reasoning）
    """
    from .tools.registry import ToolRegistry, tool_registry as default_registry

    reg: ToolRegistry = registry or default_registry
    tool_defs = tools if tools is not None else reg.defs()

    # ad-hoc 工具（tools 传入但未注册进 registry）：执行时直接调 handler
    extra_defs = {t.name: t for t in tool_defs if reg.get(t.name) is None}

    async def emit(event_type: str, **payload: Any) -> None:
        if event_sink is not None:
            await event_sink.emit(event_type, agent_key=agent_key, phase=phase, **payload)

    def record_usage(c: BaseLLMClient, resp: ChatResponse) -> None:
        """token 用量落库（fire-and-forget，recorder 自吞错）"""
        from app.services.token_usage_recorder import token_usage_recorder

        token_usage_recorder.record(
            provider=getattr(c, "protocol", "unknown"),
            model_name=getattr(resp, "model", "") or getattr(c, "model", ""),
            usage=resp.usage,
            task_id=task_id,
            user_id=user_id,
            agent_key=agent_key,
            phase=phase,
        )

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
    truncated_text_parts: List[str] = []  # 各截断轮已生成文本（耗尽时拼接降级输出）
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
        # 体积控制：messages 全文仅在本会话（run_conversation）首个请求轮携带
        # （messages_full=true），会话内后续轮次只带条数，避免多轮工具循环
        # 反复重复发送同样的大 payload。多会话 agent（如辩论辩手每轮重建
        # 历史）每次会话的首轮都会重新携带全文——否则辩论轮注入的对手
        # 报告在过程视图中不可见
        messages_full = turns == 1
        request_payload: Dict[str, Any] = {
            "tools": len(tool_defs),
            "estimated_tokens": counter.count(messages),
            "messages_full": messages_full,
        }
        if messages_full:
            request_payload["messages"] = messages_event_payload(messages)
        else:
            request_payload["messages"] = len(messages)
        await emit("llm_request", **request_payload)

        async def _call() -> ChatResponse:
            resp_local: Optional[ChatResponse] = None
            async for event in active_client.chat_stream(
                messages,
                system=system,
                tools=tool_defs or None,
                max_tokens=escalated_max_tokens or max_tokens,
                temperature=temperature,
                thinking_budget=thinking_budget,
            ):
                if event.type == "text_delta":
                    if on_text_delta:
                        on_text_delta(event.text)
                    await emit("text_delta", text=event.text)
                elif event.type == "thinking_delta":
                    await emit("thinking_delta", text=event.text)
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
        record_usage(active_client, resp)

        # 推理模型 thinking/reasoning 块（canonical 层不保留，从 raw 响应防御式提取）。
        # 必须先于 llm_response 发射：思考在生成顺序上先于正文，事件 seq 决定
        # 前端时间线与落库回放的呈现顺序
        thinking_text = _extract_thinking_text(resp)
        if thinking_text:
            await emit("thinking", text=thinking_text)

        await emit(
            "llm_response",
            stop_reason=resp.stop_reason.value,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            cache_creation_input_tokens=resp.usage.cache_creation_input_tokens,
            cache_read_input_tokens=resp.usage.cache_read_input_tokens,
            model=getattr(resp, "model", ""),
            text=resp.text(),  # 本轮最终 assistant 文本全文（纯工具轮为空串，字段恒在）
        )

        # usage 校准 token 计数
        counter.update_from_usage(resp.usage.input_tokens, len(messages))

        # ── max_output_tokens 截断恢复（对齐 claude-code 两级恢复）──
        if resp.stop_reason.value == "max_tokens":
            truncated_text_parts.append(resp.text())
            # ① 升级输出上限重发：当前值 < 模型 upper_limit 时升级到 upper_limit
            #    （每轮一次；对齐 query.ts escalate。配满上限的模型不触发，
            #    直接走恢复消息续写，省一次无意义重发）
            if escalated_max_tokens is None:
                limits_ = resolve_output_limits(
                    getattr(active_client, "model", "") or "",
                    db_max_tokens=max_tokens,
                )
                current_cap = escalated_max_tokens or max_tokens or limits_.max_tokens
                if current_cap < limits_.upper_limit:
                    escalated_max_tokens = limits_.upper_limit
                    logger.warning(
                        f"⚠️ [runner] 输出截断，升级 max_tokens {current_cap} → "
                        f"{limits_.upper_limit} 重发"
                    )
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
            # 拼接各截断轮已生成文本（此前只取最后一轮，前几轮内容被整体丢弃）
            result.final_text = "".join(truncated_text_parts).strip() or resp.text()
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
                        await emit(
                            "user_message_injected",
                            text=unwrap_system_reminder(msg.content),
                        )
                    continue
            result.final_text = resp.text()
            result.stop_reason = resp.stop_reason.value
            break

        # ── 同轮多工具：并发分区执行 ─────────────────────────────────
        outputs = await _execute_partitioned(
            reg, tool_uses, safe_map, extra_defs=extra_defs, emit=emit, task_id=task_id
        )
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
                await emit(
                    "user_message_injected",
                    text=unwrap_system_reminder(msg.content),
                )

    result.turns = min(turns, max_turns)
    return result


async def _execute_partitioned(
    reg,
    tool_uses: List[ToolUseBlock],
    safe_map: dict,
    extra_defs: Optional[dict] = None,
    task_id: str = "",
    emit: Optional[Any] = None,
) -> List[str]:
    """按并发分区执行同轮工具调用；未注册进 registry 的 ad-hoc 工具直接调 handler"""

    async def _exec(tu: ToolUseBlock) -> str:
        logger.info(f"🔧 [runner] 工具调用: {tu.name}({str(tu.input)[:500]}{'...' if len(str(tu.input)) > 500 else ''})")
        start = time.time()
        if emit is not None:
            await emit("tool_call", tool=tu.name, tool_use_id=tu.id, input=tu.input)
        try:
            if extra_defs and tu.name in extra_defs:
                result = extra_defs[tu.name].handler(**tu.input)
                if inspect.isawaitable(result):
                    result = await result
                out = str(result)
            else:
                out = await reg.execute(tu.name, tu.input, task_id=task_id)
        except Exception as e:  # noqa: BLE001 - 回传错误而非中断
            out = f"工具执行失败: {e}"
        if emit is not None:
            await emit(
                "tool_result",
                tool=tu.name,
                tool_use_id=tu.id,
                output=out[:TOOL_RESULT_MAX_CHARS],
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
