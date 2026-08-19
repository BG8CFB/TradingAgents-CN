"""并发分区测试：本地分区逻辑 + 真实 API 并发工具执行（禁止 mock）"""

import asyncio

import pytest

from app.llm import create_client, run_conversation
from app.llm.config import load_config
from app.llm.core.types import ToolDef, ToolUseBlock
from app.llm.orchestration.concurrency import partition_tool_calls, run_batches
from app.llm.tools.registry import ToolRegistry


# ---------- 本地：分区正确性 ----------


def _tu(name: str) -> ToolUseBlock:
    return ToolUseBlock(id=f"id_{name}", name=name, input={})


def test_partition_all_safe_batched_together():
    defs = {
        "a": ToolDef(name="a", description="", params_schema={}, handler=None, is_concurrency_safe=True),
        "b": ToolDef(name="b", description="", params_schema={}, handler=None, is_concurrency_safe=True),
    }
    batches = partition_tool_calls([_tu("a"), _tu("b")], lambda n: defs[n].is_concurrency_safe)
    assert len(batches) == 1
    assert batches[0].concurrent
    assert [t.name for t in batches[0].items] == ["a", "b"]


def test_partition_write_tool_serial():
    """写工具独立成串行批，且批间保序"""
    safe = {"ro1": True, "ro2": True, "write": False, "ro3": True}
    batches = partition_tool_calls([_tu("ro1"), _tu("ro2"), _tu("write"), _tu("ro3")], lambda n: safe[n])
    # ro1+ro2 并发批 → write 串行批 → ro3 单元素批
    assert [(b.concurrent, [t.name for t in b.items]) for b in batches] == [
        (True, ["ro1", "ro2"]),
        (False, ["write"]),
        (True, ["ro3"]),
    ]


def test_partition_batch_size_cap():
    """并发批上限 10：11 个安全工具拆成 10+1"""
    calls = [_tu(f"t{i}") for i in range(11)]
    batches = partition_tool_calls(calls, lambda n: True)
    assert [len(b.items) for b in batches] == [10, 1]
    assert all(b.concurrent for b in batches)


def test_run_batches_preserves_order():
    """并发执行但结果顺序与调用顺序一致"""

    async def fake(tu: ToolUseBlock) -> str:
        await asyncio.sleep(0.05 if tu.name.endswith("1") else 0)  # 故意让先发的后完成
        return tu.name

    async def main():
        batches = partition_tool_calls([_tu("x1"), _tu("x2"), _tu("x3")], lambda n: True)
        return await run_batches(batches, fake)

    assert asyncio.run(main()) == ["x1", "x2", "x3"]


# ---------- 真实 API：同轮并发安全工具 ----------


@pytest.fixture
def registry() -> ToolRegistry:
    reg = ToolRegistry()

    @reg.register(
        description="计算两个整数的和。算术加法时使用。",
        params_schema={
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
            "required": ["a", "b"],
        },
    )
    def add(a: int, b: int) -> str:
        return str(a + b)

    return reg


@pytest.mark.ai
@pytest.mark.asyncio
@pytest.mark.skipif(not load_config().api_key, reason="ARK_API_KEY 未配置")
async def test_two_tools_in_one_turn(registry):
    """真实 API：一轮要求两个加法 → 分区并发执行 → 两个结果都被使用"""
    client = create_client("anthropic")
    add_def = registry.get("add")
    result = await run_conversation(
        client,
        "请分别用工具计算 11+22 和 33+44，然后在回答中同时给出两个结果。",
        system="你是计算助手，必须调用 add 工具完成每个计算，两个计算都要调用工具。",
        registry=registry,
        tools=[
            ToolDef(
                name="add",
                description=add_def.description,
                params_schema=add_def.params_schema,
                handler=add_def.handler,
                is_concurrency_safe=True,
            )
        ],
        max_turns=6,
    )
    assert result.tool_calls_executed >= 2
    assert "33" in result.final_text and "77" in result.final_text
