"""
双协议基础对话测试：真实请求火山 Ark CodePlan（deepseek-v4-flash）

覆盖：工厂创建、非流式 chat、流式 chat_stream、usage 回传、system prompt 生效。
"""

import pytest

from app.llm import Message, Role, create_client
from app.llm.config import load_config

pytestmark = [pytest.mark.ai, pytest.mark.asyncio]

PROTOCOLS = ["anthropic", "openai"]

_config = load_config()

pytestmark = [
    pytest.mark.ai,
    pytest.mark.asyncio,
    pytest.mark.skipif(not _config.api_key, reason="ARK_API_KEY 未配置，跳过真实 API 测试"),
]


@pytest.fixture(params=PROTOCOLS)
def client(request):
    return create_client(request.param)


async def test_chat_basic(client):
    """非流式：一句话对话返回非空文本 + usage"""
    resp = await client.chat(
        [Message(role=Role.USER, content="用一句话回答：中国最长的河流是哪条？")],
        system="你是简洁的中文助手。",
        max_tokens=256,
    )
    assert resp.text(), "回复文本不应为空"
    assert "长江" in resp.text()
    assert resp.stop_reason.value == "end_turn"
    assert resp.usage.input_tokens > 0
    assert resp.usage.output_tokens > 0


async def test_chat_stream(client):
    """流式：收到文本增量 + 最终完整响应"""
    deltas = []
    final = None
    async for event in client.chat_stream(
        [Message(role=Role.USER, content="数到3，用逗号分隔，不要其他内容。")],
        system="你是简洁助手。",
        max_tokens=128,
    ):
        if event.type == "text_delta":
            deltas.append(event.text)
        elif event.type == "message":
            final = event.response
    assert deltas, "应收到文本增量"
    assert final is not None
    assert final.text().startswith("".join(deltas).strip()[:4]), "最终文本应与增量一致"


async def test_system_prompt_effect(client):
    """system prompt 生效：限定回复语言"""
    resp = await client.chat(
        [Message(role=Role.USER, content=" Say hello.")],
        system="无论用户使用什么语言，你必须只用中文回复，且不超过10个字。",
        max_tokens=128,
    )
    assert resp.text()
    # 宽松断言：回复含中文字符
    assert any("一" <= ch <= "鿿" for ch in resp.text())
