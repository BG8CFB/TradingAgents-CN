"""
按功能点组织的后端 API 端点测试

功能点：认证与用户管理
覆盖路由：POST /api/auth/login, /register, /refresh, /me 等
运行：python -m pytest tests/features/ -v
"""

import pytest
import pytest_asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI


# ============================================================
# 测试基础设施
# ============================================================

def _make_test_app():
    """创建包含 auth 路由的测试应用"""
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


def _mock_user(is_admin=False, is_active=True):
    """创建模拟用户对象"""
    user = MagicMock()
    user.id = MagicMock()
    user.id.__str__ = lambda self: "507f1f77bcf86cd799439011"
    user.username = "test_admin" if is_admin else "test_user"
    user.email = f"{'admin' if is_admin else 'user'}@test.com"
    user.is_admin = is_admin
    user.is_active = is_active
    user.preferences = MagicMock()
    user.preferences.model_dump = MagicMock(return_value={"language": "zh-CN"})
    return user


# ============================================================
# 功能点：用户登录
# ============================================================

class TestLoginFeature:
    """POST /api/auth/login - 用户登录功能"""

    @pytest.mark.asyncio
    async def test_login_success(self, auth_client):
        """正常登录应返回 token 和用户信息"""
        mock_user = _mock_user()
        with patch("app.routers.auth_db.user_service") as us, \
             patch("app.routers.auth_db.log_operation", new_callable=AsyncMock):
            us.authenticate_user = AsyncMock(return_value=mock_user)
            resp = await auth_client.post("/api/auth/login", json={
                "username": "test_user", "password": "password123"
            })
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "access_token" in body["data"]
        assert "refresh_token" in body["data"]
        assert "user" in body["data"]
        assert body["data"]["user"]["username"] == "test_user"

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, auth_client):
        """密码错误应返回 401"""
        with patch("app.routers.auth_db.user_service") as us, \
             patch("app.routers.auth_db.log_operation", new_callable=AsyncMock):
            us.authenticate_user = AsyncMock(return_value=None)
            resp = await auth_client.post("/api/auth/login", json={
                "username": "test_admin", "password": "wrong"
            })
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_login_empty_fields(self, auth_client):
        """空用户名或密码应返回 400"""
        with patch("app.routers.auth_db.log_operation", new_callable=AsyncMock):
            resp = await auth_client.post("/api/auth/login", json={
                "username": "", "password": ""
            })
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_login_response_has_expires_in(self, auth_client):
        """登录响应应包含 expires_in"""
        mock_user = _mock_user()
        with patch("app.routers.auth_db.user_service") as us, \
             patch("app.routers.auth_db.log_operation", new_callable=AsyncMock):
            us.authenticate_user = AsyncMock(return_value=mock_user)
            resp = await auth_client.post("/api/auth/login", json={
                "username": "test_admin", "password": "password123"
            })
        body = resp.json()
        assert "expires_in" in body["data"]
        assert isinstance(body["data"]["expires_in"], int)


# ============================================================
# 功能点：用户注册
# ============================================================

class TestRegisterFeature:
    """POST /api/auth/register - 用户注册功能"""

    @pytest.mark.asyncio
    async def test_register_success(self, auth_client):
        """正常注册应返回 token"""
        mock_user = _mock_user(is_admin=False)
        with patch("app.routers.auth_db.user_service") as us, \
             patch("app.routers.auth_db.log_operation", new_callable=AsyncMock):
            us.create_user = AsyncMock(return_value=mock_user)
            resp = await auth_client.post("/api/auth/register", json={
                "username": "newuser", "email": "new@test.com", "password": "password123"
            })
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "access_token" in body["data"]

    @pytest.mark.asyncio
    async def test_register_short_password(self, auth_client):
        """密码少于6位应返回 400"""
        resp = await auth_client.post("/api/auth/register", json={
            "username": "newuser", "email": "new@test.com", "password": "12345"
        })
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_register_duplicate_user(self, auth_client):
        """用户名已存在应返回 400"""
        with patch("app.routers.auth_db.user_service") as us, \
             patch("app.routers.auth_db.log_operation", new_callable=AsyncMock):
            us.create_user = AsyncMock(return_value=None)
            resp = await auth_client.post("/api/auth/register", json={
                "username": "existing", "email": "new@test.com", "password": "password123"
            })
        assert resp.status_code == 400


# ============================================================
# 功能点：Token 刷新
# ============================================================

class TestTokenRefreshFeature:
    """POST /api/auth/refresh - Token 刷新功能"""

    @pytest.mark.asyncio
    async def test_refresh_success(self, auth_client):
        """有效 refresh_token 应返回新 token"""
        from app.services.auth_service import AuthService
        token = AuthService.create_access_token(sub="test_user", expires_delta=3600)
        mock_user = _mock_user()

        with patch("app.routers.auth_db.user_service") as us:
            us.get_user_by_username = AsyncMock(return_value=mock_user)
            resp = await auth_client.post("/api/auth/refresh", json={
                "refresh_token": token
            })
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "access_token" in body["data"]

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
    async def test_get_me_success(self, auth_client):
        """认证用户应能获取自己的信息"""
        from app.services.auth_service import AuthService
        token = AuthService.create_access_token(sub="test_user")
        mock_user = _mock_user()

        with patch("app.routers.auth_db.user_service") as us:
            us.get_user_by_username = AsyncMock(return_value=mock_user)
            resp = await auth_client.get("/api/auth/me", headers={
                "Authorization": f"Bearer {token}"
            })
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["username"] == "test_user"

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
        """健康检查端点返回正确结构"""
        resp = await health_client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["status"] == "ok"
        assert "version" in body["data"]
        assert "timestamp" in body["data"]

    @pytest.mark.asyncio
    async def test_healthz_liveness(self, health_client):
        """存活探针返回 ok"""
        resp = await health_client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_readyz_readiness(self, health_client):
        """就绪探针返回 ready"""
        resp = await health_client.get("/readyz")
        assert resp.status_code == 200
        assert resp.json()["ready"] is True
