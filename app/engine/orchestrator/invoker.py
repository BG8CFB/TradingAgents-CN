"""Stage 2-4 统一 LLM 调用入口（替代旧 llm_bridge.llm_chat）。

所有业务节点经同一 run_conversation 会话循环调用模型，天然获得：
- 分层上下文压缩（micro / auto / reactive，compact/auto_compactor.py）
- max_output_tokens 截断两级恢复（升级重发 + 续写指令）
- 限流 fallback 切换（fallback_client 重放）
- 事件流（llm_request / llm_response / text_delta … 经 event_sink 可观测）
- token 用量落库（runner 内建 record_usage）

与 Phase 1（run_analyst）共用同一条调用路径——消除"Phase 1 走 runner、
Stage 2-4 单轮裸拼"的双轨状态（对齐 claude-code 单一会话循环原则）。

P3 起业务节点经 run_node_turn 装配 submit_report 提交协议（§4.6b）：
single_turn 节点 tools=[submit_report]、max_turns=2（生成 + 提交），
替代「取最后一轮回复」的隐式报告截取。
"""

from typing import Any, Dict, List, Optional

from app.constants.llm_defaults import DEFAULT_CONTEXT_WINDOW, DEFAULT_MAX_TOKENS
from app.engine.orchestrator.workflow.submission import Submission
from app.llm.core.base import BaseLLMClient
from app.llm.core.types import Message
from app.llm.runner import run_conversation
from app.llm.tools.registry import ToolRegistry


def _is_bundle(llm: object) -> bool:
    """EngineClientBundle 鸭子判定（providers.py 的 dataclass，避免循环 import）"""
    return hasattr(llm, "primary")


def _bundle_params(llm: object):
    """拆 bundle → (primary, fallback, retries, compact_config)；裸客户端走默认值"""
    bundle = llm if _is_bundle(llm) else None
    primary: BaseLLMClient = bundle.primary if bundle else llm  # type: ignore[assignment]
    fallback = bundle.fallback if bundle is not None else None
    retries = bundle.retry_times if bundle is not None else None
    compact_config = None
    if bundle is not None:
        from app.llm.compact.auto_compactor import CompactConfig

        compact_config = CompactConfig(
            context_window=getattr(bundle, "context_window", None) or DEFAULT_CONTEXT_WINDOW,
            max_output_tokens=getattr(bundle, "max_tokens", None) or DEFAULT_MAX_TOKENS,
        )
    return bundle, primary, fallback, retries, compact_config


async def run_agent_turn(
    llm: object,
    history: List[Message],
    user_message: str,
    *,
    system: str,
    task_id: str = "",
    agent_key: str = "",
    phase: str = "",
    user_id: str = "",
    event_sink: Optional[object] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    tools: Optional[List[Any]] = None,
    max_turns: int = 1,
) -> str:
    """单轮业务节点调用（经 run_conversation）。

    Args:
        llm: EngineClientBundle（推荐，携带每模型参数与 fallback）或裸 BaseLLMClient
        history: 历史消息（报告注入、辩论轮次重建等，作为会话前缀）
        user_message: 本轮触发指令（原 messages 列表的最后一条 USER）
        system: 系统提示词
        tools: 工具列表（P3 submit_report 协议经 run_node_turn 装配；缺省无工具）
        max_turns: 会话轮数上限（无工具默认 1；带提交工具的节点为 2）
        其余: 事件流与 token 用量统计上下文

    Returns:
        模型回复文本（空响应返回空串，由调用方按 H-2 语义降级）
    """
    bundle, primary, fallback, retries, compact_config = _bundle_params(llm)

    eff_max_tokens = max_tokens or (bundle.max_tokens if bundle else None) or DEFAULT_MAX_TOKENS
    eff_temperature = temperature if temperature is not None else (bundle.temperature if bundle else None)

    result = await run_conversation(
        primary,
        user_message,
        system=system,
        tools=tools if tools is not None else [],  # 必须显式置空，否则会注入默认 registry 工具
        registry=ToolRegistry(),
        max_turns=max_turns,
        max_tokens=eff_max_tokens,
        temperature=eff_temperature,
        # 思考参数已随客户端实例化烙入（providers.build_client），此处不透传；
        # fallback 备模型亦用自己的思考配置（切换即跟随，不串味）
        fallback_client=fallback,
        retry_times=retries,
        compact_config=compact_config,
        history=history,
        task_id=task_id,
        agent_key=agent_key,
        phase=phase,
        user_id=user_id,
        event_sink=event_sink,
    )
    return result.final_text or ""


async def run_node_turn(
    llm: object,
    history: List[Message],
    user_message: str,
    *,
    system: str,
    node_type: str,
    report_key: str = "",
    state: Optional[Dict[str, Any]] = None,
    task_id: str = "",
    agent_key: str = "",
    phase: str = "",
    user_id: str = "",
    event_sink: Optional[object] = None,
    display_name: str = "",
    fallback_fields: Optional[Dict[str, Any]] = None,
) -> Submission:
    """业务节点调用 + submit_report 提交协议（P3 §4.6b，替代「取最后一轮回复」）。

    装配 tools=[submit_report]、max_turns=2（生成 + 提交）；工具 handler 即时
    写黑板并发 report_ready（structured 标记）；模型到 max_turns 未调用 →
    final_text 降级（fallback_text 标记，结构化字段取 fallback_fields）。

    Args:
        node_type: submit_report 参数 schema 选型（analyst/debater/judge/trader/
            summarizer/terminal，§4.7 表）
        report_key: 主输出报告键；空 = 不写黑板（debater 由辩论组管理 rounds）
        fallback_fields: 降级时的结构化字段回退（调用方文本解析结果）

    Returns:
        Submission（content / fields / source；content 空串由调用方按 H-2 降级）
    """
    from app.engine.orchestrator.workflow.submission import (
        SubmissionBox,
        finalize_submission,
        make_submit_report_tool,
    )

    box = SubmissionBox()
    submit_tool = make_submit_report_tool(
        box,
        node_type=node_type,
        report_key=report_key,
        state=state,
        event_sink=event_sink,
        agent_key=agent_key,
        phase=phase,
        display_name=display_name,
    )
    final_text = await run_agent_turn(
        llm,
        history,
        user_message,
        system=system,
        task_id=task_id,
        agent_key=agent_key,
        phase=phase,
        user_id=user_id,
        event_sink=event_sink,
        tools=[submit_tool],
        max_turns=2,
    )
    return finalize_submission(box, final_text=final_text, fallback_fields=fallback_fields)
