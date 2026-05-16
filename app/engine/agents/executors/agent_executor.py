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
        result = executor.execute(
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
    ):
        self.llm = llm
        self.tools = tools
        self.max_iterations = max_iterations
        self.system_prompt = system_prompt
        self.rate_limiter = rate_limiter
        self.llm_provider = llm_provider
        self.inject_tools = inject_tools
        self.inject_context = inject_context or {}

        # 可插拔组件（有默认值）
        self.loop_detector = loop_detector or LoopDetector()
        self.token_budget = token_budget or TokenBudget()
        self.result_processor = result_processor or ToolResultProcessor()
        self.state_injector = state_injector or StateInjector(
            max_iterations=max_iterations
        )

        # P0 修复：bind_tools 只调用一次
        self._llm_with_tools = llm.bind_tools(tools) if tools else llm

        # 工具查找字典
        self._tool_map = {
            getattr(t, "name", None): t for t in tools if getattr(t, "name", None)
        }

        logger.info(
            f"🔧 [AgentExecutor] 初始化: max_iterations={max_iterations}, "
            f"tools={len(tools)}, bind_tools=一次绑定"
        )

    def execute(
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
            self._inject_tool_data(messages)

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
                response = self._invoke_llm(messages)
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
                # LLM 自主决定停止 — 正常结束
                logger.info(
                    f"✅ [AgentExecutor] LLM 自主停止 (迭代 {iteration}), "
                    f"报告长度: {len(response.content or '')} 字符"
                )
                final_report = response.content or ""
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
                    final_response = self._invoke_llm(messages)
                    if not (hasattr(final_response, "tool_calls") and final_response.tool_calls):
                        final_report = final_response.content or ""
                        messages.append(final_response)
                        break
                    # LLM 仍然调用工具，强制停止
                    messages.append(final_response)
                except Exception:
                    pass

                # 强制总结
                final_report = self._force_summary(messages)
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
                    # 工具未找到
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
            final_report = self._force_summary(messages)
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

    def _invoke_llm(self, messages: List[BaseMessage]) -> Any:
        """调用 LLM（带速率限制和优雅降级）"""
        if self.rate_limiter:
            try:
                return self.rate_limiter.rate_limited_call(
                    self.llm_provider,
                    self._llm_with_tools.invoke,
                    messages,
                )
            except RuntimeError as e:
                # 速率限制超时 — 优雅降级
                if "rate limit" in str(e).lower():
                    logger.warning(f"⚠️ [AgentExecutor] 速率限制触发，降级为无限制调用: {e}")
                    return self._llm_with_tools.invoke(messages)
                raise
        return self._llm_with_tools.invoke(messages)

    def _force_summary(self, messages: List[BaseMessage]) -> str:
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
            # 不绑定工具，强制纯文本输出
            response = self.llm.invoke(messages)
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

    def _inject_tool_data(self, messages: List[BaseMessage]) -> None:
        """自动注入预加载数据（委托给 simple_agent_template）"""
        try:
            from app.engine.agents.analysts.simple_agent_template import _inject_tool_data
            _inject_tool_data(
                agent_name="AgentExecutor",
                inject_tools=self.inject_tools,
                inject_context=self.inject_context,
                messages=messages,
            )
        except ImportError:
            logger.warning("⚠️ [AgentExecutor] 无法导入 _inject_tool_data, 跳过数据注入")
