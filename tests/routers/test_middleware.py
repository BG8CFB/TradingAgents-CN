"""
中间件组件测试
测试 RequestIDMiddleware、RateLimitMiddleware 和 OperationLogMiddleware
"""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from fastapi import FastAPI, Request, Response


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
    async def test_normal_request_passes_when_redis_unavailable(self, rate_limit_client):
        """Redis 不可用时请求应通过"""
        with patch("app.middleware.rate_limit._get_redis_service_safe", return_value=None):
            response = await rate_limit_client.get("/test")
            assert response.status_code == 200

    def test_endpoint_limits_configuration(self):
        """端点限流配置应包含关键端点"""
        from app.middleware.rate_limit import RateLimitMiddleware

        middleware = RateLimitMiddleware(MagicMock(), default_rate_limit=100)
        assert "/api/analysis/single" in middleware.endpoint_limits
        assert "/api/analysis/batch" in middleware.endpoint_limits
        assert "/api/auth/login" in middleware.endpoint_limits

    @pytest.mark.asyncio
    async def test_check_rate_limit_skips_when_redis_unavailable(self):
        """Redis 不可用时 check_rate_limit 应直接返回"""
        from app.middleware.rate_limit import RateLimitMiddleware

        middleware = RateLimitMiddleware(MagicMock())
        with patch("app.middleware.rate_limit._get_redis_service_safe", return_value=None):
            # 不应抛异常
            await middleware.check_rate_limit("user1", "/api/test")


class TestGetClientIP:
    """_get_client_ip 辅助函数测试"""

    def test_returns_direct_ip(self):
        """无代理时应返回客户端 IP"""
        from app.middleware.rate_limit import _get_client_ip

        request = MagicMock()
        request.client = MagicMock()
        request.client.host = "192.168.1.100"
        request.headers = {}

        result = _get_client_ip(request)
        assert result == "192.168.1.100"

    def test_trusted_proxy_reads_forwarded_for(self):
        """可信代理应读取 X-Forwarded-For 头"""
        from app.middleware.rate_limit import _get_client_ip

        request = MagicMock()
        request.client = MagicMock()
        request.client.host = "127.0.0.1"
        request.headers = {"x-forwarded-for": "10.0.0.1, 192.168.1.1"}

        result = _get_client_ip(request)
        assert result == "10.0.0.1"

    def test_trusted_proxy_reads_real_ip(self):
        """可信代理应读取 X-Real-IP 头"""
        from app.middleware.rate_limit import _get_client_ip

        request = MagicMock()
        request.client = MagicMock()
        request.client.host = "::1"
        request.headers = {"x-real-ip": "10.0.0.2"}

        result = _get_client_ip(request)
        assert result == "10.0.0.2"

    def test_untrusted_proxy_ignores_headers(self):
        """不可信代理应忽略转发头"""
        from app.middleware.rate_limit import _get_client_ip

        request = MagicMock()
        request.client = MagicMock()
        request.client.host = "203.0.113.1"
        request.headers = {"x-forwarded-for": "10.0.0.1"}

        result = _get_client_ip(request)
        assert result == "203.0.113.1"

    def test_no_client_returns_unknown(self):
        """无客户端信息应返回 unknown"""
        from app.middleware.rate_limit import _get_client_ip

        request = MagicMock()
        request.client = None
        request.headers = {}

        result = _get_client_ip(request)
        assert result == "unknown"


class TestOperationLogMiddleware:
    """OperationLogMiddleware 测试"""

    def test_default_skip_paths(self):
        """默认跳过路径应包含健康检查和文档路径"""
        from app.middleware.operation_log_middleware import OperationLogMiddleware

        middleware = OperationLogMiddleware(MagicMock())
        expected_skips = [
            "/health", "/healthz", "/readyz", "/docs", "/redoc",
            "/openapi.json",
        ]
        for path in expected_skips:
            assert path in middleware.skip_paths

    def test_custom_skip_paths(self):
        """自定义跳过路径应生效"""
        from app.middleware.operation_log_middleware import OperationLogMiddleware

        custom_paths = ["/custom/skip"]
        middleware = OperationLogMiddleware(MagicMock(), skip_paths=custom_paths)
        assert "/custom/skip" in middleware.skip_paths

    def test_should_skip_logging_for_health(self):
        """健康检查路径应跳过日志"""
        from app.middleware.operation_log_middleware import OperationLogMiddleware

        middleware = OperationLogMiddleware(MagicMock())
        request = MagicMock()
        request.url = MagicMock()
        request.url.path = "/health"
        request.method = "GET"

        result = middleware._should_skip_logging(request)
        assert result is True

    def test_should_skip_logging_for_non_api(self):
        """非 API 路径应跳过日志"""
        from app.middleware.operation_log_middleware import OperationLogMiddleware

        middleware = OperationLogMiddleware(MagicMock())
        request = MagicMock()
        request.url = MagicMock()
        request.url.path = "/favicon.ico"
        request.method = "GET"

        result = middleware._should_skip_logging(request)
        assert result is True

    def test_should_skip_logging_for_get_method(self):
        """GET 请求应跳过日志（只记录写操作）"""
        from app.middleware.operation_log_middleware import OperationLogMiddleware

        middleware = OperationLogMiddleware(MagicMock())
        request = MagicMock()
        request.url = MagicMock()
        request.url.path = "/api/analysis/tasks"
        request.method = "GET"

        result = middleware._should_skip_logging(request)
        assert result is True

    def test_should_not_skip_for_post_api(self):
        """POST API 请求不应跳过日志"""
        from app.middleware.operation_log_middleware import OperationLogMiddleware

        middleware = OperationLogMiddleware(MagicMock())
        request = MagicMock()
        request.url = MagicMock()
        request.url.path = "/api/analysis/single"
        request.method = "POST"

        result = middleware._should_skip_logging(request)
        assert result is False

    def test_should_skip_when_globally_disabled(self):
        """全局禁用时应跳过日志"""
        from app.middleware.operation_log_middleware import (
            OperationLogMiddleware, set_operation_log_enabled, OPLOG_ENABLED,
        )

        middleware = OperationLogMiddleware(MagicMock())
        request = MagicMock()
        request.url = MagicMock()
        request.url.path = "/api/analysis/single"
        request.method = "POST"

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

        middleware = OperationLogMiddleware(MagicMock())

        assert middleware._get_action_type("/api/analysis/single") == ActionType.STOCK_ANALYSIS
        assert middleware._get_action_type("/api/auth/login") == ActionType.USER_LOGIN
        assert middleware._get_action_type("/api/auth/logout") == ActionType.USER_LOGOUT
        assert middleware._get_action_type("/api/config/llm") == ActionType.CONFIG_MANAGEMENT
        assert middleware._get_action_type("/api/screening/filter") == ActionType.SCREENING

    def test_action_description_for_analysis(self):
        """分析路径的操作描述应正确"""
        from app.middleware.operation_log_middleware import OperationLogMiddleware

        middleware = OperationLogMiddleware(MagicMock())
        request = MagicMock()

        desc = middleware._get_action_description("POST", "/api/analysis/single", request)
        assert "单股分析" in desc

        desc = middleware._get_action_description("POST", "/api/analysis/batch", request)
        assert "批量分析" in desc

    def test_action_description_for_auth(self):
        """认证路径的操作描述应正确"""
        from app.middleware.operation_log_middleware import OperationLogMiddleware

        middleware = OperationLogMiddleware(MagicMock())
        request = MagicMock()

        desc = middleware._get_action_description("POST", "/api/auth/login", request)
        assert "登录" in desc

        desc = middleware._get_action_description("POST", "/api/auth/logout", request)
        assert "登出" in desc

    def test_get_client_ip(self):
        """_get_client_ip 非受信代理应忽略 X-Forwarded-For"""
        from app.middleware.operation_log_middleware import OperationLogMiddleware

        middleware = OperationLogMiddleware(MagicMock())
        request = MagicMock()
        request.headers = {"x-forwarded-for": "10.0.0.1"}
        request.client = MagicMock()
        request.client.host = "192.168.1.1"

        ip = middleware._get_client_ip(request)
        # 192.168.1.1 不是受信代理，应使用直连 IP
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

        request = MagicMock()
        request.headers = {"x-forwarded-for": "10.0.0.1"}
        request.client = MagicMock()
        request.client.host = "192.168.1.1"

        result = _get_client_ip_from_request(request)
        assert result == "192.168.1.1"

    def test_with_forwarded_for_trusted(self):
        """受信代理应使用 X-Forwarded-For"""
        from app.middleware.operation_log_middleware import _get_client_ip_from_request

        request = MagicMock()
        request.headers = {"x-forwarded-for": "10.0.0.1"}
        request.client = MagicMock()
        request.client.host = "127.0.0.1"

        result = _get_client_ip_from_request(request)
        assert result == "10.0.0.1"

    def test_with_real_ip_trusted(self):
        """受信代理无 Forwarded-For 时应使用 X-Real-IP"""
        from app.middleware.operation_log_middleware import _get_client_ip_from_request

        request = MagicMock()
        request.headers = {"x-real-ip": "10.0.0.2"}
        request.client = MagicMock()
        request.client.host = "127.0.0.1"

        result = _get_client_ip_from_request(request)
        assert result == "10.0.0.2"

    def test_with_real_ip_untrusted(self):
        """非受信代理应忽略 X-Real-IP"""
        from app.middleware.operation_log_middleware import _get_client_ip_from_request

        request = MagicMock()
        request.headers = {"x-real-ip": "10.0.0.2"}
        request.client = MagicMock()
        request.client.host = "192.168.1.1"

        result = _get_client_ip_from_request(request)
        assert result == "192.168.1.1"

    def test_with_no_headers(self):
        """无头时应使用 client.host"""
        from app.middleware.operation_log_middleware import _get_client_ip_from_request

        request = MagicMock()
        request.headers = {}
        request.client = MagicMock()
        request.client.host = "192.168.1.1"

        result = _get_client_ip_from_request(request)
        assert result == "192.168.1.1"

    def test_with_no_client(self):
        """无客户端信息应返回 unknown"""
        from app.middleware.operation_log_middleware import _get_client_ip_from_request

        request = MagicMock()
        request.headers = {}
        request.client = None

        result = _get_client_ip_from_request(request)
        assert result == "unknown"
