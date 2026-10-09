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


@dataclass
class ThinkingBlock:
    """assistant 消息中的推理/思考块。

    两个协议共用同一块类型，载荷语义按协议区分：

    - Anthropic：开启 thinking_budget 时产生并回传，signature 是多轮工具
      循环回传的必带校验字段，缺失会被 API 拒绝；
    - OpenAI 兼容（DeepSeek / vLLM / Qwen 等思考模型）：承载响应里的
      reasoning_content，thinking 存原文、signature 留空；请求侧序列化回
      assistant 消息的 reasoning_content 字段。

    为什么必须进历史：带 tools 的请求要求历史里**所有** assistant 消息的推理
    内容完整回传，缺字段会被 API 以 400 拒绝
    （"The reasoning_content in the thinking mode must be passed back to
    the API"）。展示用的 thinking 事件仍走 ChatResponse.raw，与本块互不影响。
    """

    thinking: str
    signature: str = ""


ContentBlock = TextBlock | ToolUseBlock | ToolResultBlock | ThinkingBlock


@dataclass
class Message:
    role: Role
    content: Any  # str | List[ContentBlock]；system 消息约定为 str

    def blocks(self) -> List[ContentBlock]:
        """以块列表形态访问 content（str 自动包装为单 TextBlock，单块自动包装为列表）"""
        if isinstance(self.content, str):
            return [TextBlock(text=self.content)]
        if isinstance(self.content, (TextBlock, ToolUseBlock, ToolResultBlock, ThinkingBlock)):
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
    # 缓存 token（API 回传，网关不回传时为 0）：
    # - Anthropic: cache_creation_input_tokens（写缓存）/ cache_read_input_tokens（读缓存）
    # - OpenAI: prompt_tokens_details.cached_tokens → 映射到 cache_read_input_tokens
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class ChatResponse:
    """一次 chat 调用的统一返回"""

    message: Message  # assistant 消息（blocks 含 Text/ToolUse/Thinking）
    stop_reason: StopReason
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    raw: Any = None  # 原始 SDK 响应，调试用

    def text(self) -> str:
        return "".join(b.text for b in self.message.blocks() if isinstance(b, TextBlock))

    def tool_uses(self) -> List[ToolUseBlock]:
        return [b for b in self.message.blocks() if isinstance(b, ToolUseBlock)]
