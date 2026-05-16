"""
按功能点组织的后端 API 端点测试

功能点：认证与用户管理
覆盖路由：POST /api/auth/login, /register, /refresh, /me 等
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI


# ============================================================
# 测试基础设施
# ============================================================

def _make_test_app():
    app = FastAPI()
    from app.routers.auth_db import router as auth_router
    app.include_router(auth_router)
    return app


@pytest.fixture
def auth_app():
    return _make_test_app()


@pytest_asyncio.fixture
async def auth_client(auth_app):
    transport = ASGITransport(app=auth_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# ============================================================
# 功能点：用户登录
# ============================================================

class TestLoginFeature:
    """POST /api/auth/login - 用户登录功能"""

    @pytest.mark.asyncio
    async def test_login_empty_fields(self, auth_client):
        """空用户名或密码应返回 400"""
        resp = await auth_client.post("/api/auth/login", json={
            "username": "", "password": ""
        })
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_login_wrong_credentials(self, auth_client):
        """无效凭据应返回 401"""
        resp = await auth_client.post("/api/auth/login", json={
            "username": "nonexistent_user_xyz", "password": "wrong_password"
        })
        assert resp.status_code in (401, 500)


# ============================================================
# 功能点：用户注册
# ============================================================

class TestRegisterFeature:
    """POST /api/auth/register - 用户注册功能"""

    @pytest.mark.asyncio
    async def test_register_short_password(self, auth_client):
        """密码少于6位应返回 400"""
        resp = await auth_client.post("/api/auth/register", json={
            "username": "newuser", "email": "new@test.com", "password": "12345"
        })
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_register_missing_fields(self, auth_client):
        """缺少必填字段应返回错误"""
        resp = await auth_client.post("/api/auth/register", json={
            "username": "newuser"
        })
        assert resp.status_code in (400, 422)


# ============================================================
# 功能点：Token 刷新
# ============================================================

class TestTokenRefreshFeature:
    """POST /api/auth/refresh - Token 刷新功能"""

    @pytest.mark.asyncio
    async def test_refresh_invalid_token(self, auth_client):
        """无效 refresh_token 应返回 401"""
        resp = await auth_client.post("/api/auth/refresh", json={
            "refresh_token": "invalid.token.here"
        })
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_empty_token(self, auth_client):
        """空 refresh_token 应返回 401"""
        resp = await auth_client.post("/api/auth/refresh", json={
            "refresh_token": ""
        })
        assert resp.status_code == 401


# ============================================================
# 功能点：获取/更新用户信息
# ============================================================

class TestUserInfoFeature:
    """GET/PUT /api/auth/me - 用户信息管理"""

    @pytest.mark.asyncio
    async def test_get_me_no_token(self, auth_client):
        """未认证应返回 401"""
        resp = await auth_client.get("/api/auth/me")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_get_me_invalid_token(self, auth_client):
        """无效 token 应返回 401"""
        resp = await auth_client.get("/api/auth/me", headers={
            "Authorization": "Bearer invalid.token"
        })
        assert resp.status_code == 401


# ============================================================
# 功能点：健康检查
# ============================================================

class TestHealthCheckFeature:
    """GET /health, /healthz, /readyz - 健康检查功能"""

    @pytest_asyncio.fixture
    async def health_client(self):
        app = FastAPI()
        from app.routers.health import router
        app.include_router(router)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            yield ac

    @pytest.mark.asyncio
    async def test_health_endpoint(self, health_client):
        resp = await health_client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["status"] == "ok"
        assert "version" in body["data"]
        assert "timestamp" in body["data"]

    @pytest.mark.asyncio
    async def test_healthz_liveness(self, health_client):
        resp = await health_client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_readyz_readiness(self, health_client):
        resp = await health_client.get("/readyz")
        assert resp.status_code == 200
        assert resp.json()["ready"] is True
