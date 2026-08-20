"""
子代理派发（参考 claude-code AgentTool / runAgent）

- dispatch_agent 工具：input {description, prompt, tools?, max_turns?}
- handler 递归调用 run_conversation：独立 registry 子集 + 独立 system prompt
- 返回子代理最终文本 + usage 统计 trailer（agentId 供上层追踪）
- 子代理的工具集中自动剔除 dispatch_agent（防递归编排，对齐参考项目
  ALL_AGENT_DISALLOWED_TOOLS 的默认行为）
"""

import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, List, Optional

import logging

from ..core.types import ToolDef
from ..tools.registry import ToolRegistry

if TYPE_CHECKING:
    from ..core.base import BaseLLMClient

logger = logging.getLogger("app.llm.orchestration.subagent")

SUBAGENT_SYSTEM_PROMPT = (
    "你是一个被派发来完成特定任务的子代理。根据给定的任务描述，使用可用的工具独立完成任务，"
    "完成后返回一份简明的最终报告（调用方只会看到你的报告，请只写关键结论与必要细节）。"
    "不要过度发挥，也不要半途而废。"
)

DISPATCH_AGENT_TOOL_NAME = "dispatch_agent"


@dataclass
class SubagentResult:
    agent_id: str
    report: str
    tool_calls_executed: int
    total_tokens: int
    duration_ms: int


def make_dispatch_agent_tool(
    client: "BaseLLMClient",
    registry: ToolRegistry,
    *,
    max_turns: int = 12,
    task_id: str = "",
    agent_key: str = "",
    phase: str = "",
    user_id: str = "",
    event_sink: Optional[Any] = None,
) -> ToolDef:
    """构造 dispatch_agent 工具。

    Args:
        client: 父对话使用的协议客户端（子代理复用同一客户端/模型）
        registry: 父对话的工具注册表，子代理按 tools 参数从中取子集
        max_turns: 子代理默认轮数上限
        task_id / agent_key / phase / user_id: token 用量统计上下文（透传给
            run_conversation；agent_key 会带上 .sub.{agent_id} 后缀区分父子）
        event_sink: 事件汇聚点（透传给 run_conversation，子代理过程可观测）
    """

    async def _dispatch(
        description: str, prompt: str, tools: Optional[List[str]] = None, max_turns_: int = None
    ) -> str:
        from ..runner import run_conversation  # 延迟导入避免循环依赖

        agent_id = f"agent-{uuid.uuid4().hex[:8]}"
        sub_agent_key = f"{agent_key}.sub.{agent_id}" if agent_key else agent_id
        # 子代理工具子集：剔除 dispatch_agent 防递归
        if tools:
            subset_defs = [t for t in registry.defs() if t.name in tools and t.name != DISPATCH_AGENT_TOOL_NAME]
        else:
            subset_defs = [t for t in registry.defs() if t.name != DISPATCH_AGENT_TOOL_NAME]

        sub_registry = ToolRegistry()
        sub_registry.extend(subset_defs)  # 复用 ToolDef（含 handler 与并发标记）

        logger.info(f"🤖 [subagent] {agent_id} 启动: {description} (工具: {[t.name for t in subset_defs]})")
        start = time.monotonic()
        result = await run_conversation(
            client,
            prompt,
            system=SUBAGENT_SYSTEM_PROMPT,
            registry=sub_registry,
            tools=subset_defs,
            max_turns=max_turns_ or max_turns,
            task_id=task_id,
            agent_key=sub_agent_key,
            phase=phase,
            user_id=user_id,
            event_sink=event_sink,
        )
        duration_ms = int((time.monotonic() - start) * 1000)
        total_tokens = result.total_tokens
        report = result.final_text or "(子代理完成但未返回输出)"
        logger.info(
            f"✅ [subagent] {agent_id} 完成: {result.tool_calls_executed} 工具调用, "
            f"{total_tokens} tokens, {duration_ms}ms"
        )
        return (
            f"{report}\n\n---\nagentId: {agent_id}\n"
            f"<usage>total_tokens: {total_tokens} | tool_uses: {result.tool_calls_executed} | "
            f"duration_ms: {duration_ms}</usage>"
        )

    # schema 的 max_turns 参数名去掉尾部下划线
    async def dispatch(description: str, prompt: str, tools: Optional[List[str]] = None, max_turns: int = None) -> str:
        return await _dispatch(description, prompt, tools, max_turns)

    return ToolDef(
        name=DISPATCH_AGENT_TOOL_NAME,
        description=(
            "派发一个子代理去独立完成一项任务并返回报告。"
            "适用于：可拆分出去的独立子任务、需要多步工具调用的研究型任务。"
            "prompt 要写清完整任务目标与验收标准（如同给刚接手的同事写简报）。"
            "不要用它读取特定信息（直接用对应工具更快）；结果只返回给你，需自行转述关键内容。"
        ),
        params_schema={
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "3-5 个词的任务简述"},
                "prompt": {"type": "string", "description": "完整任务描述：目标、上下文、验收标准"},
                "tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "子代理可用的工具名列表，缺省为全部可用工具",
                },
                "max_turns": {"type": "integer", "description": f"子代理轮数上限，缺省 {max_turns}"},
            },
            "required": ["description", "prompt"],
        },
        handler=dispatch,
        is_concurrency_safe=True,  # 子代理之间可并发（参考项目 Agent 工具并发安全）
    )
