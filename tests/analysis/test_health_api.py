"""
健康检查路由测试
测试 /health, /healthz, /readyz 端点
"""

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

    @pytest.mark.asyncio
    async def test_health_alias_api_path_also_works(self, health_client):
        """/api/health 是 /health 的别名路由，必须同时可用。

        防止 ruff format 误删多层装饰器导致某个路径 404（曾发生回归）。
        """
        for path in ("/health", "/api/health"):
            resp = await health_client.get(path)
            assert resp.status_code == 200, f"路径 {path} 应返回 200，实际 {resp.status_code}"
            body = resp.json()
            assert body["success"] is True
            assert body["data"]["status"] == "ok"


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

    def test_get_version_matches_pyproject(self):
        """get_version() 必须与 pyproject.toml 的 version 一致（单一来源保证）"""
        from importlib.metadata import version as pkg_version, PackageNotFoundError
        from app.routers.health import get_version

        # 包已安装时，get_version() 等价于直接读包元数据
        try:
            expected = pkg_version("tradingagents")
        except PackageNotFoundError:
            pytest.skip("tradingagents 包未安装，无法验证版本一致性")
        assert get_version() == expected
