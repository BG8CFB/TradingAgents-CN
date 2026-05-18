"""
中间件组件测试
测试 RequestIDMiddleware、RateLimitMiddleware 和 OperationLogMiddleware
使用真实的 Starlette Request 对象替代 MagicMock
"""

import asyncio
import os
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from fastapi import FastAPI, Request, Response
from starlette.testclient import TestClient


# ---------------------------------------------------------------------------
# Helper: 创建带有指定中间件的 FastAPI 应用
# ---------------------------------------------------------------------------

def _create_app_with_middleware(middleware_cls, **kwargs):
    """创建包含指定中间件的测试应用"""
    app = FastAPI()

    @app.get("/test")
    async def test_endpoint():
        return {"status": "ok"}

    @app.get("/health")
    async def health_endpoint():
        return {"status": "ok"}

    @app.get("/healthz")
    async def healthz_endpoint():
        return {"status": "ok"}

    @app.post("/api/analysis/single")
    async def analysis_single():
        return {"status": "ok"}

    @app.get("/api/stream/test")
    async def stream_endpoint():
        return {"status": "ok"}

    app.add_middleware(middleware_cls, **kwargs)
    return app


def _build_real_request(
    path: str = "/test",
    method: str = "GET",
    headers: dict = None,
    client_host: str = "192.168.1.1",
    scope_extra: dict = None,
) -> Request:
    """构建真实的 Starlette Request 对象。"""
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "server": ("testserver", 80),
        "scheme": "http",
        "client": (client_host, 12345),
    }
    if headers:
        scope["headers"] = [
            (k.lower().encode(), v.encode()) for k, v in headers.items()
        ]
    if scope_extra:
        scope.update(scope_extra)
    return Request(scope)


# ---------------------------------------------------------------------------
# Test Classes
# ---------------------------------------------------------------------------

class TestRequestIDMiddleware:
    """RequestIDMiddleware 测试"""

    @pytest.fixture
    def request_id_app(self):
        """创建带 RequestIDMiddleware 的应用"""
        from app.middleware.request_id import RequestIDMiddleware
        return _create_app_with_middleware(RequestIDMiddleware)

    @pytest_asyncio.fixture
    async def request_id_client(self, request_id_app):
        """创建测试客户端"""
        transport = ASGITransport(app=request_id_app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            yield ac

    @pytest.mark.asyncio
    async def test_adds_trace_id_header(self, request_id_client):
        """响应应包含 X-Trace-ID 头"""
        response = await request_id_client.get("/test")
        assert "x-trace-id" in response.headers
        trace_id = response.headers["x-trace-id"]
        # 应为有效的 UUID 格式
        uuid.UUID(trace_id)  # 不抛异常即通过

    @pytest.mark.asyncio
    async def test_adds_request_id_header(self, request_id_client):
        """响应应包含 X-Request-ID 头（兼容字段）"""
        response = await request_id_client.get("/test")
        assert "x-request-id" in response.headers
        assert response.headers["x-request-id"] == response.headers["x-trace-id"]

    @pytest.mark.asyncio
    async def test_adds_process_time_header(self, request_id_client):
        """响应应包含 X-Process-Time 头"""
        response = await request_id_client.get("/test")
        assert "x-process-time" in response.headers
        process_time = float(response.headers["x-process-time"])
        assert process_time >= 0

    @pytest.mark.asyncio
    async def test_trace_id_is_unique_per_request(self, request_id_client):
        """每个请求的 trace_id 应唯一"""
        response1 = await request_id_client.get("/test")
        response2 = await request_id_client.get("/test")

        id1 = response1.headers["x-trace-id"]
        id2 = response2.headers["x-trace-id"]
        assert id1 != id2

    @pytest.mark.asyncio
    async def test_successful_request_returns_200(self, request_id_client):
        """正常请求应返回 200"""
        response = await request_id_client.get("/test")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_skip_log_paths_constant_exists(self):
        """SKIP_LOG_PATHS 常量应存在"""
        from app.middleware.request_id import RequestIDMiddleware

        assert hasattr(RequestIDMiddleware, "SKIP_LOG_PATHS")
        assert isinstance(RequestIDMiddleware.SKIP_LOG_PATHS, set)
        assert "/health" in RequestIDMiddleware.SKIP_LOG_PATHS


class TestRateLimitMiddleware:
    """RateLimitMiddleware 测试"""

    @pytest.fixture
    def rate_limit_app(self):
        """创建带 RateLimitMiddleware 的应用"""
        from app.middleware.rate_limit import RateLimitMiddleware
        return _create_app_with_middleware(RateLimitMiddleware, default_rate_limit=100)

    @pytest_asyncio.fixture
    async def rate_limit_client(self, rate_limit_app):
        """创建测试客户端"""
        transport = ASGITransport(app=rate_limit_app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            yield ac

    @pytest.mark.asyncio
    async def test_skips_health_endpoints(self, rate_limit_client):
        """健康检查端点应跳过限流"""
        response = await rate_limit_client.get("/health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_normal_request_passes(self, rate_limit_client):
        """正常请求应通过（无论 Redis 是否可用都允许）"""
        response = await rate_limit_client.get("/test")
        assert response.status_code == 200

    def test_endpoint_limits_configuration(self):
        """端点限流配置应包含关键端点"""
        from app.middleware.rate_limit import RateLimitMiddleware

        # 使用 FastAPI 实例创建中间件（替代 MagicMock）
        dummy_app = FastAPI()
        middleware = RateLimitMiddleware(dummy_app, default_rate_limit=100)
        assert "/api/analysis/single" in middleware.endpoint_limits
        assert "/api/analysis/batch" in middleware.endpoint_limits
        assert "/api/auth/login" in middleware.endpoint_limits

    @pytest.mark.asyncio
    async def test_check_rate_limit_skips_when_redis_unavailable(self):
        """Redis 不可用时 check_rate_limit 应直接返回（不抛异常）"""
        import app.middleware.rate_limit as rate_limit_mod

        # 保存并设置全局标志，模拟 Redis 已确认不可用的状态
        original_redis_available = rate_limit_mod._redis_available
        original_last_check = getattr(rate_limit_mod, '_redis_last_check', 0)
        rate_limit_mod._redis_available = False
        import time
        rate_limit_mod._redis_last_check = time.time()
        try:
            from app.middleware.rate_limit import RateLimitMiddleware

            dummy_app = FastAPI()
            middleware = RateLimitMiddleware(dummy_app)

            # check_rate_limit 在 Redis 不可用时应静默通过
            # 不应抛异常
            await middleware.check_rate_limit("user1", "/api/test")
        finally:
            rate_limit_mod._redis_available = original_redis_available
            rate_limit_mod._redis_last_check = original_last_check


class TestGetClientIP:
    """_get_client_ip 辅助函数测试"""

    def test_returns_direct_ip(self):
        """无代理时应返回客户端 IP"""
        from app.middleware.rate_limit import _get_client_ip

        request = _build_real_request(client_host="192.168.1.100")
        result = _get_client_ip(request)
        assert result == "192.168.1.100"

    def test_trusted_proxy_reads_forwarded_for(self):
        """可信代理应读取 X-Forwarded-For 头"""
        from app.middleware.rate_limit import _get_client_ip

        request = _build_real_request(
            client_host="127.0.0.1",
            headers={"x-forwarded-for": "10.0.0.1, 192.168.1.1"},
        )
        result = _get_client_ip(request)
        assert result == "10.0.0.1"

    def test_trusted_proxy_reads_real_ip(self):
        """可信代理应读取 X-Real-IP 头"""
        from app.middleware.rate_limit import _get_client_ip

        request = _build_real_request(
            client_host="::1",
            headers={"x-real-ip": "10.0.0.2"},
        )
        result = _get_client_ip(request)
        assert result == "10.0.0.2"

    def test_untrusted_proxy_ignores_headers(self):
        """不可信代理应忽略转发头"""
        from app.middleware.rate_limit import _get_client_ip

        request = _build_real_request(
            client_host="203.0.113.1",
            headers={"x-forwarded-for": "10.0.0.1"},
        )
        result = _get_client_ip(request)
        assert result == "203.0.113.1"

    def test_no_client_returns_unknown(self):
        """无客户端信息应返回 unknown"""
        from app.middleware.rate_limit import _get_client_ip

        # 构建没有 client 信息的 scope
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "raw_path": b"/test",
            "query_string": b"",
            "headers": [],
            "server": ("testserver", 80),
            "scheme": "http",
            # 不设置 "client"
        }
        request = Request(scope)
        result = _get_client_ip(request)
        assert result == "unknown"


class TestOperationLogMiddleware:
    """OperationLogMiddleware 测试"""

    def _make_middleware(self):
        """创建 OperationLogMiddleware 实例"""
        from app.middleware.operation_log_middleware import OperationLogMiddleware
        dummy_app = FastAPI()
        return OperationLogMiddleware(dummy_app)

    def test_default_skip_paths(self):
        """默认跳过路径应包含健康检查和文档路径"""
        middleware = self._make_middleware()
        expected_skips = [
            "/health", "/healthz", "/readyz", "/docs", "/redoc",
            "/openapi.json",
        ]
        for path in expected_skips:
            assert path in middleware.skip_paths

    def test_custom_skip_paths(self):
        """自定义跳过路径应生效"""
        from app.middleware.operation_log_middleware import OperationLogMiddleware
        dummy_app = FastAPI()
        custom_paths = ["/custom/skip"]
        middleware = OperationLogMiddleware(dummy_app, skip_paths=custom_paths)
        assert "/custom/skip" in middleware.skip_paths

    def test_should_skip_logging_for_health(self):
        """健康检查路径应跳过日志"""
        middleware = self._make_middleware()
        request = _build_real_request(path="/health", method="GET")
        result = middleware._should_skip_logging(request)
        assert result is True

    def test_should_skip_logging_for_non_api(self):
        """非 API 路径应跳过日志"""
        middleware = self._make_middleware()
        request = _build_real_request(path="/favicon.ico", method="GET")
        result = middleware._should_skip_logging(request)
        assert result is True

    def test_should_skip_logging_for_get_method(self):
        """GET 请求应跳过日志（只记录写操作）"""
        middleware = self._make_middleware()
        request = _build_real_request(path="/api/analysis/tasks", method="GET")
        result = middleware._should_skip_logging(request)
        assert result is True

    def test_should_not_skip_for_post_api(self):
        """POST API 请求不应跳过日志"""
        middleware = self._make_middleware()
        request = _build_real_request(path="/api/analysis/single", method="POST")
        result = middleware._should_skip_logging(request)
        assert result is False

    def test_should_skip_when_globally_disabled(self):
        """全局禁用时应跳过日志"""
        from app.middleware.operation_log_middleware import (
            OperationLogMiddleware, set_operation_log_enabled,
        )

        middleware = self._make_middleware()
        request = _build_real_request(path="/api/analysis/single", method="POST")

        # 禁用
        set_operation_log_enabled(False)
        result = middleware._should_skip_logging(request)
        # 恢复
        set_operation_log_enabled(True)

        assert result is True

    def test_action_type_mapping(self):
        """路径到操作类型的映射应正确"""
        from app.middleware.operation_log_middleware import OperationLogMiddleware
        from app.models.operation_log import ActionType

        middleware = self._make_middleware()

        assert middleware._get_action_type("/api/analysis/single") == ActionType.STOCK_ANALYSIS
        assert middleware._get_action_type("/api/auth/login") == ActionType.USER_LOGIN
        assert middleware._get_action_type("/api/auth/logout") == ActionType.USER_LOGOUT
        assert middleware._get_action_type("/api/config/llm") == ActionType.CONFIG_MANAGEMENT
        assert middleware._get_action_type("/api/screening/filter") == ActionType.SCREENING

    def test_action_description_for_analysis(self):
        """分析路径的操作描述应正确"""
        from app.middleware.operation_log_middleware import OperationLogMiddleware

        middleware = self._make_middleware()
        request = _build_real_request(path="/api/analysis/single", method="POST")

        desc = middleware._get_action_description("POST", "/api/analysis/single", request)
        assert "单股分析" in desc

        desc = middleware._get_action_description("POST", "/api/analysis/batch", request)
        assert "批量分析" in desc

    def test_action_description_for_auth(self):
        """认证路径的操作描述应正确"""
        from app.middleware.operation_log_middleware import OperationLogMiddleware

        middleware = self._make_middleware()
        request = _build_real_request(path="/api/auth/login", method="POST")

        desc = middleware._get_action_description("POST", "/api/auth/login", request)
        assert "登录" in desc

        desc = middleware._get_action_description("POST", "/api/auth/logout", request)
        assert "登出" in desc

    def test_get_client_ip(self):
        """_get_client_ip 非受信代理应忽略 X-Forwarded-For"""
        from app.middleware.operation_log_middleware import OperationLogMiddleware

        middleware = self._make_middleware()
        request = _build_real_request(
            client_host="192.168.1.1",
            headers={"x-forwarded-for": "10.0.0.1"},
        )

        ip = middleware._get_client_ip(request)
        # 192.168.1.1 不是受信代理（只有 127.0.0.1 和 ::1 受信），应使用直连 IP
        assert ip == "192.168.1.1"


class TestSetOperationLogEnabled:
    """set_operation_log_enabled 函数测试"""

    def test_can_disable_and_re_enable(self):
        """应能禁用和重新启用操作日志"""
        import app.middleware.operation_log_middleware as mod

        original = mod.OPLOG_ENABLED
        try:
            mod.set_operation_log_enabled(False)
            assert mod.OPLOG_ENABLED is False

            mod.set_operation_log_enabled(True)
            assert mod.OPLOG_ENABLED is True
        finally:
            mod.OPLOG_ENABLED = original

    def test_converts_non_bool_to_bool(self):
        """非布尔值应被转换为布尔值"""
        import app.middleware.operation_log_middleware as mod

        original = mod.OPLOG_ENABLED
        try:
            mod.set_operation_log_enabled(0)
            assert mod.OPLOG_ENABLED is False

            mod.set_operation_log_enabled(1)
            assert mod.OPLOG_ENABLED is True
        finally:
            mod.OPLOG_ENABLED = original


class TestGetClientIPFromRequest:
    """_get_client_ip_from_request 辅助函数测试"""

    def test_with_forwarded_for_untrusted(self):
        """非受信代理应忽略 X-Forwarded-For"""
        from app.middleware.operation_log_middleware import _get_client_ip_from_request

        request = _build_real_request(
            client_host="192.168.1.1",
            headers={"x-forwarded-for": "10.0.0.1"},
        )
        result = _get_client_ip_from_request(request)
        assert result == "192.168.1.1"

    def test_with_forwarded_for_trusted(self):
        """受信代理应使用 X-Forwarded-For"""
        from app.middleware.operation_log_middleware import _get_client_ip_from_request

        request = _build_real_request(
            client_host="127.0.0.1",
            headers={"x-forwarded-for": "10.0.0.1"},
        )
        result = _get_client_ip_from_request(request)
        assert result == "10.0.0.1"

    def test_with_real_ip_trusted(self):
        """受信代理无 Forwarded-For 时应使用 X-Real-IP"""
        from app.middleware.operation_log_middleware import _get_client_ip_from_request

        request = _build_real_request(
            client_host="127.0.0.1",
            headers={"x-real-ip": "10.0.0.2"},
        )
        result = _get_client_ip_from_request(request)
        assert result == "10.0.0.2"

    def test_with_real_ip_untrusted(self):
        """非受信代理应忽略 X-Real-IP"""
        from app.middleware.operation_log_middleware import _get_client_ip_from_request

        request = _build_real_request(
            client_host="192.168.1.1",
            headers={"x-real-ip": "10.0.0.2"},
        )
        result = _get_client_ip_from_request(request)
        assert result == "192.168.1.1"

    def test_with_no_headers(self):
        """无头时应使用 client.host"""
        from app.middleware.operation_log_middleware import _get_client_ip_from_request

        request = _build_real_request(client_host="192.168.1.1")
        result = _get_client_ip_from_request(request)
        assert result == "192.168.1.1"

    def test_with_no_client(self):
        """无客户端信息应返回 unknown"""
        from app.middleware.operation_log_middleware import _get_client_ip_from_request

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "raw_path": b"/test",
            "query_string": b"",
            "headers": [],
            "server": ("testserver", 80),
            "scheme": "http",
        }
        request = Request(scope)
        result = _get_client_ip_from_request(request)
        assert result == "unknown"
