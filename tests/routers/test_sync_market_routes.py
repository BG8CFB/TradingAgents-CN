"""港股/美股同步路由测试 — 匹配新架构 DataInterface 路由。"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def _create_router_app(router):
    from app.routers.auth_db import get_current_user

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "test-user",
        "username": "tester",
        "is_admin": True,
    }
    return app


def _mock_refresh_result(symbol="00700", status="refreshed"):
    r = MagicMock()
    r.symbol = symbol
    r.status = status
    r.domains = {}
    r.total_latency_ms = 100
    r.source_used = "tushare_hk"
    r.fallback_from = None
    r.error = None
    return r


@pytest_asyncio.fixture
async def hk_client():
    from app.routers.hk.sync import router
    app = _create_router_app(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest_asyncio.fixture
async def us_client():
    from app.routers.us.sync import router
    app = _create_router_app(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.asyncio
async def test_hk_refresh_endpoint(hk_client):
    mock_result = _mock_refresh_result("00700", "refreshed")
    with patch("app.data.core.interface.DataInterface.refresh", new_callable=AsyncMock, return_value=mock_result):
        resp = await hk_client.post(
            "/api/hk/data/refresh/00700",
            json={"domains": ["daily_quotes"], "force": False},
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_hk_sync_trigger(hk_client):
    with patch("app.data.core.interface.DataInterface.trigger_sync", new_callable=AsyncMock, return_value={"ok": True}):
        resp = await hk_client.post(
            "/api/hk/data/sync/trigger",
            json={"domain": "daily_quotes"},
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_hk_sync_status(hk_client):
    with patch("app.data.core.interface.DataInterface.get_sync_status", new_callable=AsyncMock, return_value={"status": "ok"}):
        resp = await hk_client.get("/api/hk/data/sync/status")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_hk_sync_events(hk_client):
    with patch("app.data.core.interface.DataInterface.get_sync_status", new_callable=AsyncMock, return_value={"events": []}):
        resp = await hk_client.get("/api/hk/data/sync/events")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_us_refresh_endpoint(us_client):
    mock_result = _mock_refresh_result("AAPL", "refreshed")
    with patch("app.data.core.interface.DataInterface.refresh", new_callable=AsyncMock, return_value=mock_result):
        resp = await us_client.post(
            "/api/us/data/refresh/AAPL",
            json={"domains": ["daily_quotes"], "force": True},
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_us_sync_trigger(us_client):
    with patch("app.data.core.interface.DataInterface.trigger_sync", new_callable=AsyncMock, return_value={"ok": True}):
        resp = await us_client.post(
            "/api/us/data/sync/trigger",
            json={"domain": "basic_info", "full_sync": True},
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_us_sync_status(us_client):
    with patch("app.data.core.interface.DataInterface.get_sync_status", new_callable=AsyncMock, return_value={"status": "ok"}):
        resp = await us_client.get("/api/us/data/sync/status")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_us_sync_events(us_client):
    with patch("app.data.core.interface.DataInterface.get_sync_status", new_callable=AsyncMock, return_value={"events": []}):
        resp = await us_client.get("/api/us/data/sync/events")
    assert resp.status_code == 200
