"""
tool_use / tool_result 配对校验与修复

两种协议的 API 对配对都是强约束（不配对直接 400）：
- 孤儿 tool_use（assistant 请求了工具但没有对应结果）→ 补合成 error tool_result
- 孤儿 tool_result（结果没有对应的调用）→ 删除

参考 claude-code 的 ensureToolResultPairing（src/utils/messages.ts）。
"""

from typing import List

from ..core.types import Message, Role, ToolResultBlock, ToolUseBlock


def ensure_pairing(messages: List[Message]) -> List[Message]:
    """修复消息列表中的孤儿 tool_use / tool_result，返回修复后的新列表。幂等。"""
    called_ids = set()  # 所有 assistant 发出的 tool_use id
    answered_ids = set()  # 所有 user 回填的 tool_result 对应 id
    for msg in messages:
        for b in msg.blocks():
            if isinstance(b, ToolUseBlock):
                called_ids.add(b.id)
            elif isinstance(b, ToolResultBlock):
                answered_ids.add(b.tool_use_id)

    orphans = called_ids - answered_ids
    stale = answered_ids - called_ids

    if not orphans and not stale:
        return messages

    fixed: List[Message] = []
    for msg in messages:
        if stale and msg.role == Role.USER:
            kept = [b for b in msg.blocks() if not (isinstance(b, ToolResultBlock) and b.tool_use_id in stale)]
            if kept:
                fixed.append(Message(role=msg.role, content=kept))
        else:
            fixed.append(msg)

    # 孤儿 tool_use 补合成 error 结果（作为新 user 消息附加到末尾）
    if orphans:
        synthetic = [
            ToolResultBlock(tool_use_id=oid, content="[工具调用被中断，无执行结果]", is_error=True)
            for oid in sorted(orphans)
        ]
        fixed.append(Message(role=Role.USER, content=synthetic))

    return fixed
