"""MCP streamable-http 传输的 SDK 兼容守卫。

mcp 2.x 对该 transport 做了三处破坏性变更（函数更名 / 不再接受顶层 headers /
返回 2 元组），按 1.x 写法调用会让该类 server 整体掉线（工具列表为空）。
本测试用假 SDK 模块分别模拟两种形状，锁定调用方式不被改回单一版本。
"""

from __future__ import annotations

import sys
import types
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.llm.mcp import client as mcp_client


class _FakeStack:
    """只实现 enter_async_context 的最小 AsyncExitStack 替身。"""

    async def enter_async_context(self, cm):
        return await cm.__aenter__()


@asynccontextmanager
async def _streams():
    yield ("read-stream", "write-stream")


def _install_fake_sdk(monkeypatch, name: str, fn):
    """把 mcp.client.streamable_http 换成只暴露 name 的假模块。

    只暴露单个名字很关键：另一版本的名字必须 ImportError，才能验证回落分支。
    """
    module = types.ModuleType("mcp.client.streamable_http")
    setattr(module, name, fn)
    monkeypatch.setitem(sys.modules, "mcp.client.streamable_http", module)


class _FakeSession:
    def __init__(self, read_stream, write_stream):
        self.streams = (read_stream, write_stream)
        self.initialized = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def initialize(self):
        self.initialized = True


@pytest.mark.asyncio
async def test_mcp2_passes_headers_via_http_client(monkeypatch):
    """2.x：更名后的函数 + headers 经 http_client 承载。"""
    seen: dict = {}

    def streamable_http_client(url, http_client, terminate_on_close=True):
        seen["url"], seen["http_client"] = url, http_client
        return _streams()

    _install_fake_sdk(monkeypatch, "streamable_http_client", streamable_http_client)
    monkeypatch.setattr(mcp_client, "ClientSession", _FakeSession)
    cfg = SimpleNamespace(url="http://127.0.0.1:9/mcp", headers={"X-Token": "t"})

    session = await mcp_client.MCPManager()._connect_http(_FakeStack(), cfg)

    assert session.initialized is True, "连接后必须 initialize()"
    assert seen["url"] == cfg.url
    assert seen["http_client"] is not None, "2.x 必须经 http_client 传 headers"


@pytest.mark.asyncio
async def test_mcp1_uses_top_level_headers(monkeypatch):
    """1.x：旧函数名 + 顶层 headers 关键字 + 3 元组返回值。"""
    seen: dict = {}

    def streamablehttp_client(url, headers=None):
        seen["url"], seen["headers"] = url, headers
        return _streams()

    _install_fake_sdk(monkeypatch, "streamablehttp_client", streamablehttp_client)
    monkeypatch.setattr(mcp_client, "ClientSession", _FakeSession)
    cfg = SimpleNamespace(url="http://127.0.0.1:9/mcp", headers={"X-Token": "t"})

    session = await mcp_client.MCPManager()._connect_http(_FakeStack(), cfg)

    assert session.initialized is True
    assert seen["url"] == cfg.url
    assert seen["headers"] == {"X-Token": "t"}


@pytest.mark.asyncio
async def test_headers_default_to_empty_when_absent(monkeypatch):
    """无 headers 配置时不得让 SDK 收到 None。"""
    seen: dict = {}

    def streamable_http_client(url, http_client, terminate_on_close=True):
        seen["headers"] = dict(http_client.headers)
        return _streams()

    _install_fake_sdk(monkeypatch, "streamable_http_client", streamable_http_client)
    monkeypatch.setattr(mcp_client, "ClientSession", _FakeSession)
    cfg = SimpleNamespace(url="http://127.0.0.1:9/mcp", headers=None)

    await mcp_client.MCPManager()._connect_http(_FakeStack(), cfg)

    assert "x-token" not in seen["headers"]


def test_signature_probe_tolerates_builtin():
    """无签名对象不得抛异常（否则连接会因探针本身而失败）。"""
    assert mcp_client._expects_http_client(object()) is False
