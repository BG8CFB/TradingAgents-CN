"""
核心执行引擎

参考 claw-code conversation.rs 中 ConversationRuntime.run_turn() 的设计：
- LLM 自主决定是否停止（无 tool_calls → 自然停止）
- 迭代上限作为安全兜底
- 集成 LoopDetector（6 维循环检测）
- 集成 TokenBudget（自动上下文压缩）
- 集成 ToolResultProcessor（结果截断 + 结构化错误）
- 集成 StateInjector（执行状态注入，让 LLM 自主决策）
- bind_tools 只在循环外调用一次
- 速率限制异常优雅降级
"""

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.utils.logging_init import get_logger

from .loop_detector import LoopDetector, LoopDetectionResult, ToolCallRecord
from .state_injector import StateInjector
from .token_budget import CompactResult, TokenBudget
from .tool_result_processor import ToolResultProcessor

logger = get_logger("executors.agent_executor")

DEFAULT_MAX_ITERATIONS = 12

# ── DSML / 伪工具调用泄露检测 ──────────────────────────────────
# 某些模型（尤其是 DeepSeek 旧版 deepseek-chat）在 bind_tools 场景下，
# 不通过 API 的 tool_calls 字段返回结构化调用，而是将调用意图以
# DSML 标签格式（<｜｜DSML｜｜tool_calls>）直接输出到 content 中。
# 这不是有效的分析报告，需要检测并处理。

_DSML_PATTERN = re.compile(
    r"<｜｜DSML｜｜|"
    r"<\|.*?DSML.*?\||"
    r"<｜｜DSML｜｜tool_calls>",
    re.IGNORECASE,
)

# 更广泛的伪工具调用泄露模式（覆盖各种模型的非标准输出）
_FAKE_TOOL_CALL_PATTERNS = [
    # DeepSeek DSML 格式
    r"<｜｜DSML｜｜",
    r"<｜｜DSML｜｜tool_calls>",
    r"<｜｜DSML｜｜invoke\s+name=",
    r"<｜｜DSML｜｜parameter\s+name=",
    r"<｜｜DSML｜｜/invoke>",
    r"</｜｜DSML｜｜tool_calls>",
    # 类似的非标准 function calling 文本输出
    r"<tool_calling>",
    r"<function_call>",
    r"```tool_calls",
]


def _contains_leaked_tool_calls(content: str) -> bool:
    """检测 content 中是否包含泄露的工具调用格式（如 DSML 标签）

    Returns:
        True 表示检测到泄露，content 不是有效的分析报告
    """
    if not content:
        return False

    for pattern in _FAKE_TOOL_CALL_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            return True

    return False


def _clean_leaked_tool_calls(content: str) -> str:
    """清洗 content 中残留的伪工具调用标签

    仅作为安全兜底，优先使用 _contains_leaked_tool_calls 检测后丢弃整个响应。
    """
    if not content:
        return content

    cleaned = content
    for pattern in _FAKE_TOOL_CALL_PATTERNS:
        cleaned = re.sub(pattern + r"[^<]*?(?=</|$)", "", cleaned, flags=re.IGNORECASE)

    # 清除残留的闭合标签
    cleaned = re.sub(r"</｜｜DSML｜｜[^>]*>", "", cleaned)
    cleaned = re.sub(r"</tool_calling>", "", cleaned)
    cleaned = re.sub(r"</function_call>", "", cleaned)

    return cleaned.strip()


@dataclass
class ExecutionResult:
    """执行结果"""
    final_report: str = ""
    iterations: int = 0
    tool_calls_executed: int = 0
    loop_detected: bool = False
    loop_type: Optional[str] = None
    was_compacted: bool = False
    compact_removed: int = 0
    forced_stop: bool = False
    error: Optional[str] = None
    messages: List[BaseMessage] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return not self.error and bool(self.final_report)


class AgentExecutor:
    """
    核心执行引擎

    参考 claw-code ConversationRuntime 的设计，实现 LLM + 工具的完整执行循环。

    使用方式:
        executor = AgentExecutor(
            llm=llm, tools=tools,
            max_iterations=12,
            system_prompt="你是一个分析师...",
        )
        result = await executor.execute(
            initial_messages=[HumanMessage(content="请分析...")],
        )
        print(result.final_report)
    """

    def __init__(
        self,
        llm: Any,
        tools: List[Any],
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        system_prompt: Optional[str] = None,
        loop_detector: Optional[LoopDetector] = None,
        token_budget: Optional[TokenBudget] = None,
        result_processor: Optional[ToolResultProcessor] = None,
        state_injector: Optional[StateInjector] = None,
        rate_limiter: Any = None,
        llm_provider: str = "default",
        inject_tools: Optional[List[Any]] = None,
        inject_context: Optional[Dict[str, str]] = None,
        unavailable_tools: Optional[List[str]] = None,
    ):
        self.llm = llm
        self.tools = tools
        self.max_iterations = max_iterations
        self.system_prompt = system_prompt
        self.rate_limiter = rate_limiter
        self.llm_provider = llm_provider
        self.inject_tools = inject_tools
        self.inject_context = inject_context or {}
        self.unavailable_tools = unavailable_tools or []

        # 可插拔组件（有默认值）
        self.loop_detector = loop_detector or LoopDetector()
        self.token_budget = token_budget or TokenBudget()
        self.result_processor = result_processor or ToolResultProcessor()
        self.state_injector = state_injector or StateInjector(
            max_iterations=max_iterations
        )

        # bind_tools：只在有工具时绑定
        # 注意：空列表 [] 在 Python 中是 falsy，会跳过 bind_tools
        # 这是正确行为——没有可调用工具时不应绑定
        self._llm_with_tools = llm.bind_tools(tools) if tools else llm

        # 工具查找字典
        self._tool_map = {
            getattr(t, "name", None): t for t in tools if getattr(t, "name", None)
        }

        logger.info(
            f"🔧 [AgentExecutor] 初始化: max_iterations={max_iterations}, "
            f"tools={len(tools)}, bind_tools={'已绑定' if tools else '无工具(纯文本模式)'}"
        )

    async def execute(
        self,
        initial_messages: List[BaseMessage],
    ) -> ExecutionResult:
        """
        执行 LLM + 工具循环

        核心流程（参考 claw-code run_turn）:
        1. 构建初始消息列表
        2. 自动注入预加载数据
        3. 循环：LLM 调用 → 检查 tool_calls → 执行工具 → 回到 LLM
        4. 每轮：循环检测、token 预算检查、状态注入
        5. LLM 不产出 tool_calls 时自然停止
        6. 返回 ExecutionResult

        Args:
            initial_messages: 初始消息列表（通常包含 HumanMessage）

        Returns:
            ExecutionResult
        """
        # 复制消息列表，避免修改原始数据
        messages = list(initial_messages)

        # === 自动数据注入 ===
        if self.inject_tools:
            await self._inject_tool_data(messages)

        # === 执行循环 ===
        self.state_injector.reset()
        tool_call_records: List[ToolCallRecord] = []
        tool_call_count = 0
        iteration = 0
        final_report = ""
        loop_result = LoopDetectionResult()

        while iteration < self.max_iterations:
            iteration += 1

            # --- Token 预算检查 + 自动压缩 ---
            if self.token_budget.should_compact(messages):
                messages, compact_result = self.token_budget.compact(messages)
                if compact_result.was_compacted:
                    logger.info(
                        f"📦 [AgentExecutor] 迭代 {iteration}: 自动压缩上下文, "
                        f"移除 {compact_result.removed_count} 条消息"
                    )

            # --- 状态注入（让 LLM 知道进度） ---
            state_msg = self.state_injector.build_state_message(iteration)
            if state_msg:
                messages.append(state_msg)

            # --- LLM 调用 ---
            logger.debug(f"🧠 [AgentExecutor] 迭代 {iteration}/{self.max_iterations}")
            try:
                response = await self._invoke_llm(messages)
            except Exception as e:
                logger.error(f"❌ [AgentExecutor] LLM 调用失败: {e}", exc_info=True)
                final_report = self._extract_last_ai_content(messages)
                return ExecutionResult(
                    final_report=final_report or f"分析失败: LLM 调用异常 - {e}",
                    iterations=iteration,
                    tool_calls_executed=tool_call_count,
                    error=str(e),
                    messages=messages,
                )

            # --- 检查是否有工具调用 ---
            if not (hasattr(response, "tool_calls") and response.tool_calls):
                content = response.content or ""

                # ── DSML / 伪工具调用泄露检测 ──
                # 某些模型（DeepSeek 旧版）不通过 API 的 tool_calls 返回，
                # 而是将调用意图以 DSML 标签输出到 content 中。
                # 这不是有效的分析报告，需要尝试重试或强制总结。
                if _contains_leaked_tool_calls(content):
                    logger.warning(
                        f"🚨 [AgentExecutor] 检测到伪工具调用泄露 (DSML/非标准格式), "
                        f"迭代 {iteration}, content 前200字符: {content[:200]}"
                    )

                    # 注入纠正提示，让模型重新生成
                    messages.append(response)
                    messages.append(HumanMessage(
                        content=(
                            "⚠️ 系统检测到你的回复中包含了工具调用的内部格式标签（如 <｜｜DSML｜｜>），"
                            "这不是有效的分析报告。\n\n"
                            "请直接输出完整的分析报告文本。"
                            "不要再尝试任何工具调用格式。"
                        )
                    ))

                    # 给一次重试机会（不绑定工具，强制纯文本输出）
                    try:
                        retry_response = await self._invoke_llm_no_tools(messages)
                        retry_content = retry_response.content or ""
                        if retry_content and not _contains_leaked_tool_calls(retry_content):
                            final_report = retry_content
                            logger.info(
                                f"✅ [AgentExecutor] 重试成功，报告长度: {len(final_report)} 字符"
                            )
                            messages.append(retry_response)
                            break
                        else:
                            logger.warning("⚠️ [AgentExecutor] 重试仍包含泄露，使用强制总结")
                    except Exception as e:
                        logger.warning(f"⚠️ [AgentExecutor] 重试调用失败: {e}")

                    # 重试失败 → 强制总结
                    final_report = await self._force_summary(messages)
                    return ExecutionResult(
                        final_report=final_report,
                        iterations=iteration,
                        tool_calls_executed=tool_call_count,
                        forced_stop=True,
                        messages=messages,
                    )

                # LLM 自主决定停止 — 正常结束
                logger.info(
                    f"✅ [AgentExecutor] LLM 自主停止 (迭代 {iteration}), "
                    f"报告长度: {len(content)} 字符"
                )
                # 安全兜底：清洗可能残留的标签
                final_report = _clean_leaked_tool_calls(content)
                messages.append(response)
                break

            # --- 有工具调用 ---
            logger.info(
                f"🔧 [AgentExecutor] 检测到 {len(response.tool_calls)} 个工具调用"
            )
            messages.append(response)

            # --- 循环检测 ---
            loop_result = self.loop_detector.check(
                self._normalize_tool_calls(response.tool_calls),
                tool_call_records,
            )
            if loop_result.is_loop:
                logger.warning(
                    f"🚨 [AgentExecutor] 循环检测触发: {loop_result.loop_type} — "
                    f"{loop_result.message}"
                )
                # 注入循环警告
                messages.append(HumanMessage(content=loop_result.message))
                # 给 LLM 一次机会自主停止
                try:
                    final_response = await self._invoke_llm(messages)
                    if not (hasattr(final_response, "tool_calls") and final_response.tool_calls):
                        loop_content = final_response.content or ""
                        if _contains_leaked_tool_calls(loop_content):
                            logger.warning("🚨 [AgentExecutor] 循环恢复后仍检测到 DSML 泄露，跳过")
                        else:
                            final_report = _clean_leaked_tool_calls(loop_content)
                            messages.append(final_response)
                            break
                    # LLM 仍然调用工具，强制停止
                    messages.append(final_response)
                except Exception as e:
                    logger.debug(f"LLM 循环后调用失败: {e}")
                    pass

                # 强制总结
                final_report = await self._force_summary(messages)
                return ExecutionResult(
                    final_report=final_report,
                    iterations=iteration,
                    tool_calls_executed=tool_call_count,
                    loop_detected=True,
                    loop_type=loop_result.loop_type,
                    forced_stop=True,
                    messages=messages,
                )

            # --- 执行工具调用 ---
            for tool_call in response.tool_calls:
                tool_name, tool_args, tool_call_id = self._parse_tool_call(tool_call)
                if not tool_name:
                    continue

                tool = self._tool_map.get(tool_name)
                if tool:
                    try:
                        raw_result = tool.invoke(tool_args)
                        processed = self.result_processor.process_success(
                            raw_result, tool_name
                        )
                        tool_call_count += 1

                        # 记录到循环检测器
                        tool_call_records.append(ToolCallRecord(
                            tool_name=tool_name,
                            args=tool_args,
                            is_error=False,
                        ))
                        self.state_injector.record_tool_call(
                            tool_name, tool_args, success=True
                        )

                        messages.append(ToolMessage(
                            content=processed.content,
                            tool_call_id=tool_call_id,
                            name=tool_name,
                        ))
                        logger.info(
                            f"✅ [AgentExecutor] {tool_name} 执行成功 "
                            f"(第{tool_call_count}次) {processed}"
                        )

                    except Exception as e:
                        processed = self.result_processor.process_error(
                            e, tool_name
                        )
                        tool_call_count += 1

                        tool_call_records.append(ToolCallRecord(
                            tool_name=tool_name,
                            args=tool_args,
                            is_error=True,
                        ))
                        self.state_injector.record_tool_call(
                            tool_name, tool_args, success=False
                        )

                        messages.append(ToolMessage(
                            content=processed.content,
                            tool_call_id=tool_call_id,
                            name=tool_name,
                        ))
                        logger.warning(
                            f"⚠️ [AgentExecutor] {tool_name} 执行失败: {e}"
                        )
                else:
                    # 工具未找到 — 检查是否为已预注入的内置工具
                    from app.engine.tools.builtin.registry import get_spec_by_id
                    if get_spec_by_id(tool_name):
                        messages.append(ToolMessage(
                            content=f"该数据已在上下文中预加载，请直接使用已有的数据进行分析。",
                            tool_call_id=tool_call_id,
                            name=tool_name,
                        ))
                        logger.info(f"ℹ️ [AgentExecutor] LLM 尝试调用已预注入的内置工具: {tool_name}")
                        continue

                    processed = self.result_processor.process_not_found(tool_name)
                    messages.append(ToolMessage(
                        content=processed.content,
                        tool_call_id=tool_call_id,
                        name=tool_name,
                    ))
                    logger.warning(f"⚠️ [AgentExecutor] 工具未找到: {tool_name}")

        # === 循环结束 ===
        if not final_report:
            # 达到迭代上限
            logger.warning(
                f"⚠️ [AgentExecutor] 达到最大迭代次数 {self.max_iterations}, "
                f"执行强制总结"
            )
            final_report = await self._force_summary(messages)
            return ExecutionResult(
                final_report=final_report,
                iterations=iteration,
                tool_calls_executed=tool_call_count,
                forced_stop=True,
                messages=messages,
            )

        # Token 预算统计
        budget_status = self.token_budget.estimate(messages)
        logger.info(
            f"📊 [AgentExecutor] 执行完成: {iteration} 迭代, "
            f"{tool_call_count} 工具调用, {budget_status}"
        )

        return ExecutionResult(
            final_report=final_report,
            iterations=iteration,
            tool_calls_executed=tool_call_count,
            messages=messages,
        )

    async def _invoke_llm(self, messages: List[BaseMessage]) -> Any:
        """调用 LLM（带速率限制和优雅降级），同步调用包装在线程池中避免阻塞事件循环"""
        loop = asyncio.get_running_loop()
        if self.rate_limiter:
            try:
                return await loop.run_in_executor(
                    None,
                    lambda: self.rate_limiter.rate_limited_call(
                        self.llm_provider,
                        self._llm_with_tools.invoke,
                        messages,
                    ),
                )
            except RuntimeError as e:
                # 速率限制超时 — 优雅降级
                if "rate limit" in str(e).lower():
                    logger.warning(f"⚠️ [AgentExecutor] 速率限制触发，降级为无限制调用: {e}")
                    return await loop.run_in_executor(
                        None, self._llm_with_tools.invoke, messages
                    )
                raise
        return await loop.run_in_executor(None, self._llm_with_tools.invoke, messages)

    async def _invoke_llm_no_tools(self, messages: List[BaseMessage]) -> Any:
        """调用 LLM（不绑定工具），用于强制纯文本输出的场景

        当模型出现工具调用泄露（DSML 格式等）时，使用不带 bind_tools 的
        LLM 实例重新调用，确保模型输出纯文本报告而非伪工具调用格式。
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.llm.invoke, messages)

    async def _force_summary(self, messages: List[BaseMessage]) -> str:
        """强制生成总结报告"""
        prompt = HumanMessage(
            content=(
                "🚨【系统紧急指令】🚨\n"
                "请立即停止调用任何工具，基于已获取的所有工具结果，"
                "生成最终分析报告。\n"
                "不要再调用任何工具！直接输出完整的分析报告内容。"
            )
        )
        messages.append(prompt)
        try:
            loop = asyncio.get_running_loop()
            # 不绑定工具，强制纯文本输出
            response = await loop.run_in_executor(None, self.llm.invoke, messages)
            return response.content or "分析失败: 无法生成报告"
        except Exception as e:
            logger.error(f"❌ [AgentExecutor] 强制总结失败: {e}")
            return self._extract_last_ai_content(messages) or f"分析失败: {e}"

    def _extract_last_ai_content(self, messages: List[BaseMessage]) -> str:
        """从消息历史中提取最后一条 AI 消息的内容"""
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content:
                return msg.content
        return ""

    def _parse_tool_call(self, tool_call: Any) -> tuple:
        """解析工具调用对象"""
        if isinstance(tool_call, dict):
            return (
                tool_call.get("name", ""),
                tool_call.get("args", {}),
                tool_call.get("id", ""),
            )
        return (
            getattr(tool_call, "name", ""),
            getattr(tool_call, "args", {}),
            getattr(tool_call, "id", ""),
        )

    def _normalize_tool_calls(self, tool_calls: list) -> List[Dict]:
        """将 tool_calls 标准化为 dict 列表"""
        result = []
        for tc in tool_calls:
            if isinstance(tc, dict):
                result.append(tc)
            else:
                result.append({
                    "name": getattr(tc, "name", ""),
                    "args": getattr(tc, "args", {}),
                    "id": getattr(tc, "id", ""),
                })
        return result

    async def _inject_tool_data(self, messages: List[BaseMessage]) -> None:
        """自动注入预加载数据 + 不可用工具通知（委托给 simple_agent_template）"""
        try:
            from app.engine.agents.analysts.simple_agent_template import _inject_tool_data
            await _inject_tool_data(
                agent_name="AgentExecutor",
                inject_tools=self.inject_tools,
                unavailable_tool_ids=self.unavailable_tools,
                inject_context=self.inject_context,
                messages=messages,
            )
        except ImportError:
            logger.warning("⚠️ [AgentExecutor] 无法导入 _inject_tool_data, 跳过数据注入")
