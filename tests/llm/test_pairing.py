"""
配对修复测试（本地逻辑，无需 API）

覆盖：孤儿 tool_use 补合成 error tool_result；孤儿 tool_result 被删除；已配对不受影响。
"""

from app.llm import Message, Role, ToolResultBlock, ToolUseBlock
from app.llm.tools.pairing import ensure_pairing


def test_orphan_tool_use_gets_synthetic_result():
    """assistant 发起 tool_use 但没有对应结果 → 补合成 error tool_result"""
    messages = [
        Message(role=Role.USER, content="查一下天气"),
        Message(role=Role.ASSISTANT, content=[ToolUseBlock(id="tu_1", name="weather", input={"city": "北京"})]),
    ]
    fixed = ensure_pairing(messages)
    assert len(fixed) == 3
    last = fixed[-1]
    assert last.role == Role.USER
    tr = [b for b in last.blocks() if isinstance(b, ToolResultBlock)]
    assert len(tr) == 1
    assert tr[0].tool_use_id == "tu_1"
    assert tr[0].is_error is True


def test_orphan_tool_result_removed():
    """tool_result 没有对应的 tool_use → 删除"""
    messages = [
        Message(role=Role.USER, content="你好"),
        Message(
            role=Role.USER,
            content=[ToolResultBlock(tool_use_id="tu_ghost", content="无主结果")],
        ),
        Message(role=Role.ASSISTANT, content="你好！"),
    ]
    fixed = ensure_pairing(messages)
    all_results = [b for m in fixed for b in m.blocks() if isinstance(b, ToolResultBlock)]
    assert all_results == [], "孤儿 tool_result 应被删除"


def test_paired_messages_untouched():
    """已正确配对 → 原样返回（幂等）"""
    messages = [
        Message(role=Role.USER, content="查天气"),
        Message(role=Role.ASSISTANT, content=[ToolUseBlock(id="tu_1", name="weather", input={})]),
        Message(role=Role.USER, content=[ToolResultBlock(tool_use_id="tu_1", content="晴")]),
    ]
    assert ensure_pairing(messages) is messages
