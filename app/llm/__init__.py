"""
app.llm — 独立 LLM 客户端层（OpenAI 协议 + Anthropic 协议）

对外只暴露本模块的导出，消费方不感知协议实现：
    from app.llm import create_client, run_conversation, tool_registry

目录结构与依赖方向见各子模块 docstring（protocols/tools/compact → core，单向）。
"""

from .config import LLMConfig, load_config
from .core.base import BaseLLMClient, StreamEvent
from .core.errors import (
    AuthError,
    ContextWindowExceededError,
    LLMError,
    ProtocolError,
    RateLimitError,
    TimeoutError_,
)
from .core.factory import create_client
from .core.types import (
    ChatResponse,
    Message,
    Role,
    StopReason,
    TextBlock,
    ToolDef,
    ToolResultBlock,
    ToolUseBlock,
    Usage,
)

__all__ = [
    "create_client",
    "load_config",
    "LLMConfig",
    "BaseLLMClient",
    "StreamEvent",
    "ChatResponse",
    "Message",
    "Role",
    "StopReason",
    "TextBlock",
    "ToolDef",
    "ToolResultBlock",
    "ToolUseBlock",
    "Usage",
    "LLMError",
    "AuthError",
    "RateLimitError",
    "ContextWindowExceededError",
    "ProtocolError",
    "TimeoutError_",
    "run_conversation",
    "tool_registry",
]


def __getattr__(name: str):
    # 延迟导入：runner / registry 引用协议实现，避免包导入即拉起 SDK
    if name == "run_conversation":
        from .runner import run_conversation

        return run_conversation
    if name == "tool_registry":
        from .tools.registry import tool_registry

        return tool_registry
    raise AttributeError(f"module 'app.llm' has no attribute '{name}'")
