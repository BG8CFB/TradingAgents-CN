"""
token 计数：API usage 权威 + chars/4 增量估算

策略（参考 claude-code tokenCountWithEstimation）：
- 记录最近一次 API 回传的精确 usage 及其覆盖到的消息位置
- 其后的新增消息用 chars/4 粗估累加
"""

from dataclasses import dataclass
from typing import List

from ..core.types import Message, ToolResultBlock, ToolUseBlock


def estimate_messages_tokens(messages: List[Message]) -> int:
    """chars/4 粗估整个消息列表的 token 数（无 tokenizer 依赖）"""
    chars = 0
    for m in messages:
        for b in m.blocks():
            if isinstance(b, ToolUseBlock):
                import json

                chars += len(b.name) + len(json.dumps(b.input, ensure_ascii=False))
            elif isinstance(b, ToolResultBlock):
                chars += len(b.content)
            else:
                chars += len(getattr(b, "text", "") or "")
    return chars // 4


@dataclass
class TokenCounter:
    """跨轮维护的 token 计数器（runner 持有一个实例）"""

    # 最近一次 API 回传的权威 usage（input_tokens 已覆盖前 N 条消息）
    authoritative_input_tokens: int = 0
    authoritative_upto: int = 0  # 权威值覆盖到的消息数（含该轮 assistant 响应）

    def update_from_usage(self, input_tokens: int, messages_count: int) -> None:
        """每次 chat 返回后调用：messages_count 为本次请求发出的消息数+1（响应）"""
        if input_tokens and messages_count >= self.authoritative_upto:
            self.authoritative_input_tokens = input_tokens
            self.authoritative_upto = messages_count

    def count(self, messages: List[Message]) -> int:
        """当前消息列表的 token 估算：权威前缀 + 增量粗估"""
        if len(messages) <= self.authoritative_upto:
            return self.authoritative_input_tokens
        prefix = self.authoritative_input_tokens
        tail = messages[self.authoritative_upto :]
        return prefix + estimate_messages_tokens(tail)
