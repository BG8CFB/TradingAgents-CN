"""港股/美股同步路由测试 — 使用真实 DataInterface + SimulatedMongoDB。

设计原则：不使用 unittest.mock。通过 inject_sim_db 注入内存 MongoDB，
DataInterface 走真实代码路径。dependency_overrides 是 FastAPI 官方推荐
的测试方式，不属于 unittest.mock。
"""

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.data.core.interface import DataInterface


def _create_router_app(router):
    app = FastAPI()
    app.include_router(router)
    return app


@pytest_asyncio.fixture
async def hk_client(inject_sim_db):
    """创建港股测试客户端，注入 SimulatedMongoDB 到 DataInterface。"""
    from app.routers.hk.sync import router

    DataInterface.reset_instance()
    di = DataInterface()
    DataInterface._instance = di

    app = _create_router_app(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    DataInterface.reset_instance()


@pytest_asyncio.fixture
async def us_client(inject_sim_db):
    """创建美股测试客户端，注入 SimulatedMongoDB 到 DataInterface。"""
    from app.routers.us.sync import router

    DataInterface.reset_instance()
    di = DataInterface()
    DataInterface._instance = di

    app = _create_router_app(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

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


class TestHKSyncTrigger:
    """港股同步触发路由。"""

    @pytest.mark.asyncio
    async def test_sync_trigger_returns_200(self, hk_client, inject_sim_db):
        resp = await hk_client.post(
            "/api/hk/data/sync/trigger",
            json={"domain": "daily_quotes"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True

    @pytest.mark.asyncio
    async def test_sync_trigger_writes_event(self, hk_client, inject_sim_db):
        await hk_client.post(
            "/api/hk/data/sync/trigger",
            json={"domain": "daily_quotes"},
        )

        events = await inject_sim_db["sync_events"].find({}).to_list()
        assert len(events) >= 1
        event = events[-1]
        assert event["market"] == "HK"
        assert event["domain"] == "daily_quotes"
        assert event["event_type"] == "SYNC_START"
        assert event["task_id"].startswith("sync_HK_daily_quotes_")


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
            "/api/hk/data/sync/trigger",
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
            "/api/hk/data/sync/trigger",
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


class TestUSSyncTrigger:
    """美股同步触发路由。"""

    @pytest.mark.asyncio
    async def test_sync_trigger_returns_200(self, us_client, inject_sim_db):
        resp = await us_client.post(
            "/api/us/data/sync/trigger",
            json={"domain": "basic_info", "full_sync": True},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_sync_trigger_writes_event(self, us_client, inject_sim_db):
        await us_client.post(
            "/api/us/data/sync/trigger",
            json={"domain": "basic_info"},
        )

        events = await inject_sim_db["sync_events"].find({}).to_list()
        assert len(events) >= 1
        event = events[-1]
        assert event["market"] == "US"
        assert event["domain"] == "basic_info"


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
