"""港股/美股同步路由测试 — 使用真实 DataInterface + SimulatedMongoDB + 真实 DB 鉴权。

设计原则（已迁移到真实 DB 鉴权路径）：
- 不使用 unittest.mock / MagicMock
- 不使用 dependency_overrides 模拟身份
- 通过 inject_sim_db 注入内存 MongoDB（DataInterface 走真实代码路径）
- 预置真实管理员用户文档（含真实密码哈希）+ 真实 JWT，走完整 get_current_user/require_admin 流程
"""

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.data.core.interface import DataInterface


# 管理员测试用户数据（与真实 DB 鉴权路径对齐）
_ADMIN_FIXTURE = {
    "id": "507f1f77bcf86cd799430001",
    "username": "sync_routes_test_admin",
    "email": "sync_routes_admin@test.com",
    "is_admin": True,
    "preferences": {"language": "zh-CN", "ui_theme": "light"},
}


async def _setup_admin_user(sim_db) -> str:
    """预置管理员用户文档并返回真实 JWT。

    复用 conftest.admin_client 的模式：真实密码哈希 + 真实 access_token，
    让请求走完整的 get_current_user → user_service.get_user_by_username → require_admin 路径。
    """
    from app.services.user_service import user_service
    from app.services.auth_service import AuthService
    from app.utils.passwords import hash_password
    from app.utils.time_utils import now_utc

    user_service.set_database(sim_db)
    user_doc = {
        "_id": _ADMIN_FIXTURE["id"],
        "username": _ADMIN_FIXTURE["username"],
        "email": _ADMIN_FIXTURE["email"],
        "hashed_password": hash_password("Admin@1234"),
        "is_admin": True,
        "is_active": True,
        "created_at": now_utc(),
        "preferences": _ADMIN_FIXTURE.get("preferences", {}),
    }
    await sim_db.users.insert_one(user_doc)
    return AuthService.create_access_token(sub=_ADMIN_FIXTURE["username"])


async def _teardown_admin_user(sim_db, original_db) -> None:
    from app.services.user_service import user_service
    user_service.set_database(original_db)
    try:
        await sim_db.users.delete_many({"username": _ADMIN_FIXTURE["username"]})
    except Exception as exc:
        import motor.errors
        if not isinstance(exc, motor.errors.PyMongoError):
            raise


def _create_router_app(router) -> tuple[FastAPI, str]:
    """创建测试 app：不做 dependency_overrides，依赖真实 JWT 解析路径。

    返回 (app, csrf_token)：CSRF token 由调用方注入到 AsyncClient 的 cookies 与 header，
    详见 hk_client / us_client fixture。

    注意：CSRF 双提交 Cookie 必须在请求头中提供，否则会被 CSRFMiddleware 拒绝。
    """
    from app.middleware.csrf import generate_csrf_token
    csrf_token = generate_csrf_token("test-session-fixed")

    app = FastAPI()
    app.include_router(router)
    return app, csrf_token


@pytest_asyncio.fixture
async def hk_client(inject_sim_db):
    """创建港股测试客户端：真实 DataInterface + 真实 DB 鉴权路径。"""
    from app.routers.hk.sync import router
    from app.services.user_service import user_service
    from app.middleware.csrf import (
        CSRF_COOKIE_NAME,
        CSRF_HEADER_NAME,
    )

    DataInterface.reset_instance()
    di = DataInterface()
    DataInterface._instance = di

    original_db = user_service.db
    admin_token = await _setup_admin_user(inject_sim_db)

    try:
        app, csrf_token = _create_router_app(router)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            client.cookies.set(CSRF_COOKIE_NAME, csrf_token)
            client.headers.update({
                CSRF_HEADER_NAME: csrf_token,
                "Authorization": f"Bearer {admin_token}",
            })
            yield client
    finally:
        await _teardown_admin_user(inject_sim_db, original_db)
        DataInterface.reset_instance()


@pytest_asyncio.fixture
async def us_client(inject_sim_db):
    """创建美股测试客户端：真实 DataInterface + 真实 DB 鉴权路径。"""
    from app.routers.us.sync import router
    from app.services.user_service import user_service
    from app.middleware.csrf import (
        CSRF_COOKIE_NAME,
        CSRF_HEADER_NAME,
    )

    DataInterface.reset_instance()
    di = DataInterface()
    DataInterface._instance = di

    original_db = user_service.db
    admin_token = await _setup_admin_user(inject_sim_db)

    try:
        app, csrf_token = _create_router_app(router)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            client.cookies.set(CSRF_COOKIE_NAME, csrf_token)
            client.headers.update({
                CSRF_HEADER_NAME: csrf_token,
                "Authorization": f"Bearer {admin_token}",
            })
            yield client
    finally:
        await _teardown_admin_user(inject_sim_db, original_db)
        DataInterface.reset_instance()


# ---------------------------------------------------------------------------
# 港股路由测试
# ---------------------------------------------------------------------------


class TestHKRefresh:
    """港股按需刷新路由。"""

    @pytest.mark.asyncio
    async def test_refresh_endpoint_returns_200(self, hk_client, inject_sim_db):
        resp = await hk_client.post(
            "/api/hk/data/refresh/00700",
            json={"domains": ["daily_quotes"], "force": False},
        )
        assert resp.status_code == 200

        body = resp.json()
        assert body["success"] is True
        assert body["data"]["symbol"] == "00700"

    @pytest.mark.asyncio
    async def test_refresh_endpoint_response_structure(self, hk_client, inject_sim_db):
        resp = await hk_client.post(
            "/api/hk/data/refresh/00700",
            json={"domains": ["daily_quotes"], "force": False},
        )
        body = resp.json()["data"]
        assert "symbol" in body
        assert "status" in body
        assert "domains" in body
        assert "duration_ms" in body


class TestHKSyncStatus:
    """港股同步状态路由。"""

    @pytest.mark.asyncio
    async def test_sync_status_returns_200(self, hk_client, inject_sim_db):
        resp = await hk_client.get("/api/hk/data/sync/status")
        assert resp.status_code == 200

        body = resp.json()
        assert body["success"] is True
        assert "items" in body["data"]
        assert "total" in body["data"]

    @pytest.mark.asyncio
    async def test_sync_status_with_domain_filter(self, hk_client, inject_sim_db):
        await hk_client.post(
            "/api/hk/data/sync/daily_quotes",
            json={"domain": "daily_quotes"},
        )

        resp = await hk_client.get("/api/hk/data/sync/status?domain=daily_quotes")
        assert resp.status_code == 200


class TestHKSyncEvents:
    """港股同步事件路由。"""

    @pytest.mark.asyncio
    async def test_sync_events_returns_200(self, hk_client, inject_sim_db):
        resp = await hk_client.get("/api/hk/data/sync/events")
        assert resp.status_code == 200

        body = resp.json()
        assert body["success"] is True
        assert "items" in body["data"]

    @pytest.mark.asyncio
    async def test_sync_events_after_trigger(self, hk_client, inject_sim_db):
        await hk_client.post(
            "/api/hk/data/sync/daily_quotes",
            json={"domain": "daily_quotes"},
        )

        resp = await hk_client.get("/api/hk/data/sync/events")
        body = resp.json()["data"]
        assert body["total"] >= 1


# ---------------------------------------------------------------------------
# 美股路由测试
# ---------------------------------------------------------------------------


class TestUSRefresh:
    """美股按需刷新路由。"""

    @pytest.mark.asyncio
    async def test_refresh_endpoint_returns_200(self, us_client, inject_sim_db):
        resp = await us_client.post(
            "/api/us/data/refresh/AAPL",
            json={"domains": ["daily_quotes"], "force": True},
        )
        assert resp.status_code == 200

        body = resp.json()
        assert body["success"] is True
        assert body["data"]["symbol"] == "AAPL"


class TestUSSyncStatus:
    """美股同步状态路由。"""

    @pytest.mark.asyncio
    async def test_sync_status_returns_200(self, us_client, inject_sim_db):
        resp = await us_client.get("/api/us/data/sync/status")
        assert resp.status_code == 200


class TestUSSyncEvents:
    """美股同步事件路由。"""

    @pytest.mark.asyncio
    async def test_sync_events_returns_200(self, us_client, inject_sim_db):
        resp = await us_client.get("/api/us/data/sync/events")
        assert resp.status_code == 200
