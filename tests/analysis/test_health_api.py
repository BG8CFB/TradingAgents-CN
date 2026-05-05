"""
健康检查路由测试
测试 /health, /healthz, /readyz 端点
"""

import time
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from fastapi import FastAPI


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def health_app():
    """创建仅包含 health 路由的 FastAPI 应用"""
    app = FastAPI()
    from app.routers.health import router as health_router
    app.include_router(health_router)
    return app


@pytest_asyncio.fixture
async def health_client(health_app):
    """健康检查测试客户端"""
    transport = ASGITransport(app=health_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Test Classes
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    """GET /health 端点测试"""

    @pytest.mark.asyncio
    async def test_health_returns_200(self, health_client):
        """健康检查应返回 200 状态码"""
        response = await health_client.get("/health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_health_has_success_field(self, health_client):
        """响应体包含 success 字段且为 True"""
        response = await health_client.get("/health")
        body = response.json()
        assert body["success"] is True

    @pytest.mark.asyncio
    async def test_health_has_data_with_status(self, health_client):
        """响应体 data 字段包含 status 值为 ok"""
        response = await health_client.get("/health")
        body = response.json()
        assert "data" in body
        assert body["data"]["status"] == "ok"

    @pytest.mark.asyncio
    async def test_health_has_version(self, health_client):
        """响应体 data 字段包含 version 字符串"""
        response = await health_client.get("/health")
        body = response.json()
        assert "data" in body
        assert "version" in body["data"]
        assert isinstance(body["data"]["version"], str)

    @pytest.mark.asyncio
    async def test_health_has_timestamp(self, health_client):
        """响应体 data 字段包含 timestamp 整数"""
        response = await health_client.get("/health")
        body = response.json()
        assert "data" in body
        assert "timestamp" in body["data"]
        assert isinstance(body["data"]["timestamp"], int)

    @pytest.mark.asyncio
    async def test_health_has_service_name(self, health_client):
        """响应体 data 字段包含 service 名称"""
        response = await health_client.get("/health")
        body = response.json()
        assert body["data"]["service"] == "TradingAgents-CN API"

    @pytest.mark.asyncio
    async def test_health_has_message(self, health_client):
        """响应体包含 message 字段"""
        response = await health_client.get("/health")
        body = response.json()
        assert "message" in body
        assert isinstance(body["message"], str)

    @pytest.mark.asyncio
    async def test_health_timestamp_is_recent(self, health_client):
        """timestamp 应接近当前时间"""
        before = int(time.time()) - 5
        response = await health_client.get("/health")
        after = int(time.time()) + 5
        body = response.json()
        assert before <= body["data"]["timestamp"] <= after


class TestHealthzEndpoint:
    """GET /healthz 存活探针测试"""

    @pytest.mark.asyncio
    async def test_healthz_returns_200(self, health_client):
        """存活探针应返回 200"""
        response = await health_client.get("/healthz")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_healthz_has_status_ok(self, health_client):
        """存活探针返回 status: ok"""
        response = await health_client.get("/healthz")
        body = response.json()
        assert body["status"] == "ok"


class TestReadyzEndpoint:
    """GET /readyz 就绪探针测试"""

    @pytest.mark.asyncio
    async def test_readyz_returns_200(self, health_client):
        """就绪探针应返回 200"""
        response = await health_client.get("/readyz")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_readyz_has_ready_true(self, health_client):
        """就绪探针返回 ready: True"""
        response = await health_client.get("/readyz")
        body = response.json()
        assert body["ready"] is True


class TestGetVersion:
    """get_version() 函数测试"""

    def test_get_version_returns_string(self):
        """get_version 应返回非空字符串"""
        from app.routers.health import get_version
        version = get_version()
        assert isinstance(version, str)
        assert len(version) > 0

    def test_get_version_fallback_on_missing_file(self):
        """VERSION 文件不存在时返回默认版本号"""
        from app.routers import health as health_module
        with patch.object(health_module, "Path") as mock_path_cls:
            # 模拟 Path(__file__).parent.parent.parent / "VERSION" 不存在
            mock_version_file = mock_path_cls.return_value.parent.parent.parent.__truediv__.return_value
            mock_version_file.exists.return_value = False
            version = health_module.get_version()
            assert version == "0.1.16"
