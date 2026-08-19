"""
上下文压缩测试

- microcompact：本地逻辑，构造真实消息结构验证清理行为
- LLM compact：真实请求（小阈值触发），验证摘要产出与历史替换
"""

import pytest

from app.llm import Message, Role, TextBlock, ToolResultBlock, ToolUseBlock, create_client
from app.llm.compact.auto_compactor import AutoCompactor, CompactConfig
from app.llm.compact.token_counter import TokenCounter, estimate_messages_tokens
from app.llm.config import load_config

_config = load_config()

pytestmark_local = pytest.mark.asyncio


# ── 本地：microcompact ─────────────────────────────────────────────


def _long_history() -> list:
    """真实结构的对话历史：6 轮，每轮含大体积 tool_result"""
    messages = []
    for i in range(6):
        messages.append(Message(role=Role.USER, content=f"第{i}轮问题：" + "数据" * 500))
        messages.append(
            Message(
                role=Role.ASSISTANT,
                content=[
                    TextBlock(text=f"第{i}轮分析"),
                    ToolUseBlock(id=f"tu_{i}", name="query", input={"i": i}),
                ],
            )
        )
        messages.append(
            Message(
                role=Role.USER,
                content=[ToolResultBlock(tool_use_id=f"tu_{i}", content="结果数据" * 500)],
            )
        )
    return messages


def test_microcompact_clears_old_tool_results():
    client = create_client("anthropic") if _config.api_key else None
    compactor = AutoCompactor(client, TokenCounter(), CompactConfig())
    messages = _long_history()
    result = compactor._microcompact(messages)

    results = [b for m in result for b in m.blocks() if isinstance(b, ToolResultBlock)]
    cleared = [b for b in results if b.content.startswith("[Old tool result content cleared]")]
    assert len(cleared) >= 2, "较旧的 tool_result 应被清理"
    # 最近几轮保留原文
    assert any("结果数据" in b.content for b in results)
    assert estimate_messages_tokens(result) < estimate_messages_tokens(messages)


def test_microcompact_noop_when_nothing_to_clear():
    compactor = AutoCompactor(None, TokenCounter(), CompactConfig())
    messages = [Message(role=Role.USER, content="你好"), Message(role=Role.ASSISTANT, content="你好！")]
    assert compactor._microcompact(messages) is messages


# ── 真实 API：LLM compact ──────────────────────────────────────────

ai = pytest.mark.skipif(not _config.api_key, reason="ARK_API_KEY 未配置")


@pytest.mark.asyncio
@ai
@pytest.mark.parametrize("protocol", ["anthropic", "openai"])
async def test_llm_compact_replaces_history(protocol):
    """小阈值强制触发 LLM 压缩：历史被替换为 system + 摘要 user 消息"""
    client = create_client(protocol)
    # 阈值压到极小，跳过 microcompact（min_tool_results_to_clear 设大）
    cfg = CompactConfig(context_window=600, max_output_tokens=100, buffer=0, min_tool_results_to_clear=999)
    compactor = AutoCompactor(client, TokenCounter(), cfg)

    messages = [
        Message(role=Role.USER, content="我正在分析平安银行(000001)的股价走势，用户关注2024年报。"),
        Message(role=Role.ASSISTANT, content="好的，我已了解：分析平安银行，重点看2024年报数据。"),
        Message(role=Role.USER, content="请特别关注不良贷款率和净利润增速。"),
        Message(role=Role.ASSISTANT, content="明白，将聚焦不良贷款率与净利润增速两个指标。"),
    ]
    new_messages, llm_compacted = await compactor.compact(messages, system="你是股票分析助手。")

    assert llm_compacted is True
    assert len(new_messages) == 2  # [system, summary user]
    assert new_messages[0].role == Role.SYSTEM
    summary = new_messages[1].content
    assert isinstance(summary, str) and len(summary) > 20
    # 摘要应保留关键事实
    assert "平安银行" in summary or "000001" in summary
