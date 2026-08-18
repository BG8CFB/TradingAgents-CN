"""WebSocket token 提取单元测试（FC-1 修复验证）

验证 ``_extract_token_from_websocket`` 正确从 Sec-WebSocket-Protocol
子协议头或 query string 回退中提取 JWT token。

遵循真实测试铁律：不 mock 被测对象，使用真实 FastAPI 应用 + TestClient。
"""

# 测试环境变量必须在导入 app 模块之前设置（与 conftest.py 同步）
import os
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("MONGODB_HOST", "localhost")
os.environ.setdefault("MONGODB_PORT", "27017")
os.environ.setdefault("MONGODB_USERNAME", "admin")
os.environ.setdefault("MONGODB_PASSWORD", "tradingagents123")
os.environ.setdefault("MONGODB_DATABASE", "tradingagents_test")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")
os.environ.setdefault("REDIS_PASSWORD", "tradingagents123")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-testing-only")
os.environ.setdefault("CSRF_SECRET", "test-csrf-secret-for-testing-only")
os.environ.setdefault("MONGODB_ENABLED", "true")
os.environ.setdefault("REDIS_ENABLED", "true")

import pytest
from fastapi import FastAPI, WebSocket
from starlette.testclient import TestClient

from app.routers.websocket_notifications import _extract_token_from_websocket


# ---------------------------------------------------------------------------
# Helper: 创建最小 FastAPI 应用暴露 token 提取结果
# ---------------------------------------------------------------------------

def _create_token_echo_app() -> FastAPI:
    """创建用于测试 token 提取的临时应用。

    WS 端点 /echo-token 调用被测函数并返回提取的 token（或 null）。
    """
    app = FastAPI()

    @app.websocket("/echo-token")
    async def echo_token(websocket: WebSocket):
        await websocket.accept()
        token = _extract_token_from_websocket(websocket)
        await websocket.send_text(token if token else "null")
        await websocket.close()

    return app


# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------

class TestExtractTokenFromWebsocket:
    """_extract_token_from_websocket 行为测试"""

    @pytest.fixture
    def client(self):
        app = _create_token_echo_app()
        return TestClient(app)

    def test_extracts_token_from_subprotocol_bearer_prefix(self, client):
        """子协议头 ['bearer', '<token>'] 应正确提取 token。"""
        fake_token = "eyJhbGciOiJIUzI1NiJ9.test_payload.signature"
        with client.websocket_connect(
            "/echo-token", subprotocols=["bearer", fake_token]
        ) as ws:
            result = ws.receive_text()
        assert result == fake_token

    def test_extracts_token_from_subprotocol_single_value(self, client):
        """子协议头只传一个值时（无 bearer 前缀），应取最后一个值。"""
        fake_token = "single_protocol_token_value"
        with client.websocket_connect(
            "/echo-token", subprotocols=[fake_token]
        ) as ws:
            result = ws.receive_text()
        assert result == fake_token

    def test_extracts_token_from_query_fallback(self, client):
        """无子协议头时，应从 query string 回退提取 token。"""
        fake_token = "query_fallback_token_abc123"
        with client.websocket_connect(
            f"/echo-token?token={fake_token}"
        ) as ws:
            result = ws.receive_text()
        assert result == fake_token

    def test_subprotocol_takes_priority_over_query(self, client):
        """同时存在子协议和 query token 时，子协议优先。"""
        subprotocol_token = "subprotocol_priority_token"
        query_token = "query_should_be_ignored"
        with client.websocket_connect(
            f"/echo-token?token={query_token}",
            subprotocols=["bearer", subprotocol_token]
        ) as ws:
            result = ws.receive_text()
        assert result == subprotocol_token

    def test_returns_none_when_no_token_anywhere(self, client):
        """子协议和 query 均无 token 时返回 None。"""
        with client.websocket_connect("/echo-token") as ws:
            result = ws.receive_text()
        assert result == "null"

    def test_returns_none_when_subprotocol_empty_and_no_query(self, client):
        """子协议列表为空且无 query 时返回 None。"""
        with client.websocket_connect(
            "/echo-token", subprotocols=[]
        ) as ws:
            result = ws.receive_text()
        assert result == "null"
