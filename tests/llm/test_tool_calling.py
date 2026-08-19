"""
工具调用全链路测试：真实请求 + 真实工具执行（禁止 mock）

覆盖：模型发起 tool_use → runner 执行注册工具 → 回填 tool_result → 模型产出最终文本；
tool_use_id 配对正确；多轮循环自然终止。
"""

import pytest

from app.llm import Message, Role, ToolUseBlock, create_client, run_conversation
from app.llm.config import load_config
from app.llm.tools.registry import ToolRegistry

pytestmark = [
    pytest.mark.ai,
    pytest.mark.asyncio,
    pytest.mark.skipif(not load_config().api_key, reason="ARK_API_KEY 未配置"),
]


@pytest.fixture
def registry() -> ToolRegistry:
    """独立注册表（不影响全局），注册真实工具：加法计算器"""
    reg = ToolRegistry()

    @reg.register(
        description="计算两个整数的和。当用户要求加法计算时使用。",
        params_schema={
            "type": "object",
            "properties": {
                "a": {"type": "integer", "description": "第一个加数"},
                "b": {"type": "integer", "description": "第二个加数"},
            },
            "required": ["a", "b"],
        },
    )
    def add_numbers(a: int, b: int) -> str:
        return str(a + b)

    return reg


@pytest.fixture(params=["anthropic", "openai"])
def client(request):
    return create_client(request.param)


async def test_tool_roundtrip(client, registry):
    """完整回路：提问加法 → 模型调工具 → 拿到 37 → 自然终止"""
    result = await run_conversation(
        client,
        "请计算 15 加 22 等于多少？必须调用工具计算，不要心算。",
        system="你是计算助手，遇到算术必须调用 add_numbers 工具。",
        registry=registry,
        tools=registry.defs(),
        max_turns=6,
    )
    assert result.tool_calls_executed >= 1, "模型应至少调用一次工具"
    assert "37" in result.final_text
    assert result.stop_reason == "end_turn"
    # 历史：user → assistant(tool_use) → user(tool_result) → assistant(text)
    assert len(result.messages) >= 4
    # tool_use 与 tool_result 一一配对
    used_ids = [b.id for m in result.messages for b in m.blocks() if isinstance(b, ToolUseBlock)]
    answered_ids = [b.tool_use_id for m in result.messages for b in m.blocks() if hasattr(b, "tool_use_id")]
    assert set(used_ids) == set(answered_ids)


async def test_multi_turn_conversation(client, registry):
    """多轮对话：传入历史延续上下文"""
    history = [
        Message(role=Role.USER, content="我叫小明，请记住。"),
        Message(role=Role.USER, content="我叫小明"),
    ]
    # 第二条重复 user 消息不合规，改为标准交替
    history = [
        Message(role=Role.USER, content="我叫小明，请记住我的名字。"),
    ]
    result = await run_conversation(
        client,
        "我叫什么名字？",
        system="你是问答助手。",
        registry=registry,
        tools=[],
        history=history,
        max_turns=4,
    )
    assert "小明" in result.final_text


async def test_unknown_tool_returns_error_text(client, registry):
    """runner 执行未知工具：回传错误文本而非中断"""

    out = await registry.execute("no_such_tool", {})
    assert "未知工具" in out
