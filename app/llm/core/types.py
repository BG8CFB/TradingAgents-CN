"""
协议中立的消息与工具数据模型

以 Anthropic content blocks 为 canonical 形态（参考 claude-code 的设计）：
- Text / ToolUse / ToolResult 三种内容块
- OpenAI 协议侧做双向转换（protocols/openai_client.py）
- 本模块不依赖任何 SDK
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class StopReason(str, Enum):
    """停止原因（对齐 Anthropic 语义，OpenAI 侧映射 finish_reason）"""

    END_TURN = "end_turn"  # 自然结束（无工具调用）
    TOOL_USE = "tool_use"  # 模型请求调用工具
    MAX_TOKENS = "max_tokens"  # 达到输出上限
    STOP_SEQUENCE = "stop_sequence"
    OTHER = "other"


@dataclass
class TextBlock:
    text: str


@dataclass
class ToolUseBlock:
    """assistant 消息中的工具调用请求"""

    id: str  # tool_use_id，与 ToolResultBlock.tool_use_id 一一对应
    name: str
    input: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResultBlock:
    """user 消息中的工具执行结果，回填给模型"""

    tool_use_id: str
    content: str
    is_error: bool = False


ContentBlock = TextBlock | ToolUseBlock | ToolResultBlock


@dataclass
class Message:
    role: Role
    content: Any  # str | List[ContentBlock]；system 消息约定为 str

    def blocks(self) -> List[ContentBlock]:
        """以块列表形态访问 content（str 自动包装为单 TextBlock，单块自动包装为列表）"""
        if isinstance(self.content, str):
            return [TextBlock(text=self.content)]
        if isinstance(self.content, (TextBlock, ToolUseBlock, ToolResultBlock)):
            return [self.content]
        return list(self.content)


@dataclass
class ToolDef:
    """统一的工具定义（注册侧），协议转换由各 client 完成"""

    name: str
    description: str
    params_schema: Dict[str, Any] = field(default_factory=dict)  # JSON Schema
    handler: Any = None  # callable(input_dict) -> str，同步或异步
    # 并发安全声明（参考 claude-code 的 isConcurrencySafe）：
    # True = 只读/无副作用，可与同批其他安全工具并发执行；False = 串行
    is_concurrency_safe: bool = False


@dataclass
class Usage:
    """token 用量：API 回传值为权威，估算值仅作增量"""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class ChatResponse:
    """一次 chat 调用的统一返回"""

    message: Message  # assistant 消息（blocks 含 Text/ToolUse）
    stop_reason: StopReason
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    raw: Any = None  # 原始 SDK 响应，调试用

    def text(self) -> str:
        return "".join(b.text for b in self.message.blocks() if isinstance(b, TextBlock))

    def tool_uses(self) -> List[ToolUseBlock]:
        return [b for b in self.message.blocks() if isinstance(b, ToolUseBlock)]
