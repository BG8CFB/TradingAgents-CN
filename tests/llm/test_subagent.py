"""子代理测试：真实 API，父代理 dispatch_agent 委托 → 子代理带工具完成 → 父代理引用结果"""

import pytest

from app.llm import create_client
from app.llm.config import load_config
from app.llm.orchestration.subagent import make_dispatch_agent_tool
from app.llm.runner import run_conversation
from app.llm.tools.registry import ToolRegistry

pytestmark = [
    pytest.mark.ai,
    pytest.mark.asyncio,
    pytest.mark.skipif(not load_config().api_key, reason="ARK_API_KEY 未配置"),
]


@pytest.fixture
def registry() -> ToolRegistry:
    reg = ToolRegistry()

    @reg.register(
        description="计算两个整数的乘积。乘法运算时使用。",
        params_schema={
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
            "required": ["a", "b"],
        },
    )
    def multiply(a: int, b: int) -> str:
        return str(a * b)

    return reg


async def test_dispatch_agent_delegates_and_reports(registry):
    """父代理不直接算，委托子代理用 multiply 工具完成任务"""
    client = create_client("anthropic")
    dispatch = make_dispatch_agent_tool(client, registry)
    all_tools = registry.defs() + [dispatch]

    result = await run_conversation(
        client,
        "请派一个子代理去计算 123 乘以 456（子代理必须使用 multiply 工具），然后引用它的报告给出最终答案。",
        system="你是调度助手。所有计算必须委托给子代理完成，不要自己心算。",
        registry=registry,
        tools=all_tools,
        max_turns=8,
    )
    used = {b.name for m in result.messages for b in m.blocks() if getattr(b, "name", None)}
    assert "dispatch_agent" in used
    assert "56088" in result.final_text
    assert result.total_tokens > 0
