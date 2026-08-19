"""协议层 Usage 缓存字段解析测试（unit，无网络、无 mock 库）

用测试代码内构造的响应对象（SimpleNamespace，SDK 响应的同构数据结构）
直接驱动两个协议客户端的 _response_to_canonical 真实代码路径。
"""

from types import SimpleNamespace

import pytest

from app.llm.core.types import Usage
from app.llm.protocols.anthropic_client import AnthropicLLMClient
from app.llm.protocols.openai_client import OpenAILLMClient


def _anthropic_resp(**usage_fields):
    """构造 Anthropic SDK Message 响应的同构对象"""
    usage = SimpleNamespace(
        input_tokens=usage_fields.get("input_tokens", 100),
        output_tokens=usage_fields.get("output_tokens", 50),
        cache_creation_input_tokens=usage_fields.get("cache_creation_input_tokens", 0),
        cache_read_input_tokens=usage_fields.get("cache_read_input_tokens", 0),
    )
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text="hello")],
        stop_reason="end_turn",
        usage=usage,
        model="claude-sonnet-4-5",
    )


def _openai_resp(**usage_fields):
    """构造 OpenAI SDK ChatCompletion 响应的同构对象"""
    details = SimpleNamespace(
        cached_tokens=usage_fields.get("cached_tokens", 0)
    )
    usage = SimpleNamespace(
        prompt_tokens=usage_fields.get("prompt_tokens", 100),
        completion_tokens=usage_fields.get("completion_tokens", 50),
        prompt_tokens_details=details if usage_fields.get("has_details", True) else None,
    )
    choice = SimpleNamespace(
        message=SimpleNamespace(content="hello", tool_calls=None),
        finish_reason="stop",
    )
    return SimpleNamespace(choices=[choice], usage=usage, model="gpt-test")


class TestUsageDataclass:
    def test_default_cache_fields_zero(self):
        u = Usage()
        assert u.cache_creation_input_tokens == 0
        assert u.cache_read_input_tokens == 0
        assert u.total == 0


class TestAnthropicUsageParsing:
    def _client(self):
        # 不发起网络请求：__init__ 只构造 SDK 客户端对象
        return AnthropicLLMClient(api_key="test-key", base_url="http://localhost:1", model="claude-test")

    def test_cache_fields_parsed(self):
        resp = self._client()._response_to_canonical(
            _anthropic_resp(input_tokens=1000, cache_creation_input_tokens=200, cache_read_input_tokens=3000)
        )
        assert resp.usage.input_tokens == 1000
        assert resp.usage.cache_creation_input_tokens == 200
        assert resp.usage.cache_read_input_tokens == 3000

    def test_cache_fields_default_zero(self):
        resp = self._client()._response_to_canonical(_anthropic_resp())
        assert resp.usage.cache_creation_input_tokens == 0
        assert resp.usage.cache_read_input_tokens == 0


class TestOpenAIUsageParsing:
    def _client(self):
        return OpenAILLMClient(api_key="test-key", base_url="http://localhost:1", model="gpt-test")

    def test_cached_tokens_mapped_to_cache_read(self):
        resp = self._client()._response_to_canonical(
            _openai_resp(prompt_tokens=5000, cached_tokens=4000)
        )
        assert resp.usage.input_tokens == 5000
        assert resp.usage.cache_read_input_tokens == 4000
        assert resp.usage.cache_creation_input_tokens == 0  # OpenAI 无写缓存概念

    def test_missing_prompt_tokens_details_tolerated(self):
        resp = self._client()._response_to_canonical(
            _openai_resp(has_details=False)
        )
        assert resp.usage.input_tokens == 100
        assert resp.usage.cache_read_input_tokens == 0

    def test_usage_none_tolerated(self):
        r = _openai_resp()
        r.usage = None
        resp = self._client()._response_to_canonical(r)
        assert resp.usage.input_tokens == 0


@pytest.mark.asyncio
async def test_anthropic_stream_message_start_cache_fields():
    """流式 message_start 事件中的缓存 token 应进入最终 usage（真实 chat_stream 装配路径）"""
    client = AnthropicLLMClient(api_key="test-key", base_url="http://localhost:1", model="claude-test")

    # 构造流事件序列（对齐 anthropic SDK 事件对象形状）
    class _FakeStream:
        def __init__(self, events):
            self._events = events

        async def __aiter__(self):
            for e in self._events:
                yield e

    class _FakeMessages:
        def stream(self, **params):
            return _FakeStreamMgr()

    class _FakeStreamMgr:
        async def __aenter__(self):
            events = [
                SimpleNamespace(
                    type="message_start",
                    message=SimpleNamespace(
                        model="claude-test",
                        usage=SimpleNamespace(
                            input_tokens=800,
                            output_tokens=0,
                            cache_creation_input_tokens=100,
                            cache_read_input_tokens=2000,
                        ),
                    ),
                ),
                SimpleNamespace(
                    type="message_delta",
                    delta=SimpleNamespace(stop_reason="end_turn"),
                    usage=SimpleNamespace(output_tokens=64, input_tokens=None,
                                          cache_creation_input_tokens=None,
                                          cache_read_input_tokens=None),
                ),
            ]
            return _FakeStream(events)

        async def __aexit__(self, *args):
            return False

    client._client = SimpleNamespace(messages=_FakeMessages())

    final = None
    async for ev in client.chat_stream([], system="s"):
        if ev.type == "message":
            final = ev.response
    assert final is not None
    assert final.usage.input_tokens == 800
    assert final.usage.output_tokens == 64
    # message_delta 的 usage 不携带缓存字段，message_start 的值必须保留
    assert final.usage.cache_creation_input_tokens == 100
    assert final.usage.cache_read_input_tokens == 2000
