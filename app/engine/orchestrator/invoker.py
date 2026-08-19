"""Stage 2-4 统一 LLM 调用入口（替代旧 llm_bridge.llm_chat）。

所有业务节点经同一 run_conversation 会话循环调用模型，天然获得：
- 分层上下文压缩（micro / auto / reactive，compact/auto_compactor.py）
- max_output_tokens 截断两级恢复（升级重发 + 续写指令）
- 限流 fallback 切换（fallback_client 重放）
- 事件流（llm_request / llm_response / text_delta … 经 event_sink 可观测）
- token 用量落库（runner 内建 record_usage）

与 Phase 1（run_analyst）共用同一条调用路径——消除"Phase 1 走 runner、
Stage 2-4 单轮裸拼"的双轨状态（对齐 claude-code 单一会话循环原则）。
"""

from typing import List, Optional

from app.constants.llm_defaults import DEFAULT_CONTEXT_WINDOW, DEFAULT_MAX_TOKENS
from app.llm.core.base import BaseLLMClient
from app.llm.core.types import Message
from app.llm.runner import run_conversation
from app.llm.tools.registry import ToolRegistry


def _is_bundle(llm: object) -> bool:
    """EngineClientBundle 鸭子判定（providers.py 的 dataclass，避免循环 import）"""
    return hasattr(llm, "primary")


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
) -> str:
    """单轮业务节点调用（经 run_conversation，无工具）。

    Args:
        llm: EngineClientBundle（推荐，携带每模型参数与 fallback）或裸 BaseLLMClient
        history: 历史消息（报告注入、辩论轮次重建等，作为会话前缀）
        user_message: 本轮触发指令（原 messages 列表的最后一条 USER）
        system: 系统提示词
        其余: 事件流与 token 用量统计上下文

    Returns:
        模型回复文本（空响应返回空串，由调用方按 H-2 语义降级）
    """
    bundle = llm if _is_bundle(llm) else None
    primary: BaseLLMClient = bundle.primary if bundle else llm  # type: ignore[assignment]
    fallback = bundle.fallback if bundle is not None else None
    retries = bundle.retry_times if bundle is not None else None

    eff_max_tokens = max_tokens or (bundle.max_tokens if bundle else None) or DEFAULT_MAX_TOKENS
    eff_temperature = temperature if temperature is not None else (bundle.temperature if bundle else None)

    # 压缩配置与 Phase 1（agents.py）同源：bundle 携带该模型真实
    # context_window/max_tokens（limits/catalog 解析），大窗口分级 buffer 由此生效
    compact_config = None
    if bundle is not None:
        from app.llm.compact.auto_compactor import CompactConfig

        compact_config = CompactConfig(
            context_window=getattr(bundle, "context_window", None) or DEFAULT_CONTEXT_WINDOW,
            max_output_tokens=getattr(bundle, "max_tokens", None) or DEFAULT_MAX_TOKENS,
        )

    result = await run_conversation(
        primary,
        user_message,
        system=system,
        tools=[],  # 业务节点无工具；必须显式置空，否则会注入默认 registry 工具
        registry=ToolRegistry(),
        max_turns=1,
        max_tokens=eff_max_tokens,
        temperature=eff_temperature,
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
