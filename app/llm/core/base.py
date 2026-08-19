"""
LLM 客户端抽象基类

约定：
- chat()        非流式，返回完整 ChatResponse
- chat_stream() 流式，yield 文本增量与结构化事件（工具调用块在流结束后产出）
- 输入输出均为 core.types 的协议中立模型，SDK 类型不出现在接口上
"""

from abc import ABC, abstractmethod
from typing import AsyncIterator, List, Optional

from .types import ChatResponse, Message, ToolDef


class StreamEvent:
    """流式事件：文本增量 / 单轮结束（携带 usage 与完整响应）"""

    __slots__ = ("type", "text", "response")

    def __init__(self, type_: str, text: str = "", response: Optional[ChatResponse] = None):
        self.type = type_  # "text_delta" | "message"
        self.text = text
        self.response = response


class BaseLLMClient(ABC):
    """协议无关的 LLM 客户端接口"""

    protocol: str = ""  # "anthropic" | "openai"

    @abstractmethod
    async def chat(
        self,
        messages: List[Message],
        *,
        system: Optional[str] = None,
        tools: Optional[List[ToolDef]] = None,
        max_tokens: Optional[int] = None,  # None=用客户端实例烙入值
        temperature: Optional[float] = None,
        **kwargs,
    ) -> ChatResponse:
        """非流式对话。system 以独立参数传入（两种协议均为顶层概念）。"""

    @abstractmethod
    def chat_stream(
        self,
        messages: List[Message],
        *,
        system: Optional[str] = None,
        tools: Optional[List[ToolDef]] = None,
        max_tokens: Optional[int] = None,  # None=用客户端实例烙入值
        temperature: Optional[float] = None,
        **kwargs,
    ) -> AsyncIterator[StreamEvent]:
        """流式对话。yield StreamEvent；最后一条 type=="message" 携带完整 ChatResponse。"""

    @abstractmethod
    async def count_tokens(self, messages: List[Message]) -> int:
        """估算消息列表的 token 数（精确值由 usage 回传，见 compact/token_counter.py）"""
