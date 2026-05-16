"""
健康检查路由测试
测试 /health, /healthz, /readyz 端点
"""

import time
import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI


@pytest_asyncio.fixture
async def health_client():
    app = FastAPI()
    from app.routers.health import router
    app.include_router(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


class TestHealthEndpoint:
    """测试 GET /health 端点"""

    @pytest.mark.asyncio
    async def test_health_returns_success(self, health_client):
        resp = await health_client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["status"] == "ok"

    @pytest.mark.asyncio
    async def test_health_has_version(self, health_client):
        resp = await health_client.get("/health")
        body = resp.json()
        assert "version" in body["data"]
        assert len(body["data"]["version"]) > 0

    @pytest.mark.asyncio
    async def test_health_has_timestamp(self, health_client):
        resp = await health_client.get("/health")
        body = resp.json()
        assert "timestamp" in body["data"]


class TestHealthzEndpoint:
    """测试 GET /healthz 存活探针"""

    @pytest.mark.asyncio
    async def test_healthz_returns_ok(self, health_client):
        resp = await health_client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestReadyzEndpoint:
    """测试 GET /readyz 就绪探针"""

    @pytest.mark.asyncio
    async def test_readyz_returns_ready(self, health_client):
        resp = await health_client.get("/readyz")
        assert resp.status_code == 200
        assert resp.json()["ready"] is True


class TestGetVersion:
    """get_version() 函数测试"""

    def test_get_version_returns_string(self):
        from app.routers.health import get_version
        version = get_version()
        assert isinstance(version, str)
        assert len(version) > 0

    def test_get_version_fallback_on_missing_file(self):
        """VERSION 文件不存在时返回默认版本号"""
        import tempfile
        import shutil
        from pathlib import Path
        from app.routers import health as health_module

        # 临时修改 __file__ 指向一个不存在的路径
        original_file = health_module.__file__
        try:
            # 创建临时目录结构，不包含 VERSION 文件
            tmp_dir = tempfile.mkdtemp()
            health_module.__file__ = os.path.join(tmp_dir, "health.py")
            version = health_module.get_version()
            assert version == "0.1.16"
        finally:
            health_module.__file__ = original_file
            shutil.rmtree(tmp_dir, ignore_errors=True)
