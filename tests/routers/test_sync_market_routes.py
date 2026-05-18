import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


class _DeleteResult:
    def __init__(self, deleted_count: int):
        self.deleted_count = deleted_count


class _FakeCollection:
    def __init__(self, *, symbols=None, codes=None, total=0, valid=0, latest_doc=None, deleted=0):
        self._symbols = symbols or []
        self._codes = codes or []
        self._total = total
        self._valid = valid
        self._latest_doc = latest_doc
        self._deleted = deleted
        self.delete_queries = []

    async def distinct(self, field: str):
        if field == "symbol":
            return self._symbols
        if field == "code":
            return self._codes
        return []

    async def count_documents(self, query):
        if not query:
            return self._total
        updated_at = query.get("updated_at", {})
        if "$gte" in updated_at:
            return self._valid
        return 0

    async def find_one(self, *args, **kwargs):
        return self._latest_doc

    async def delete_many(self, query):
        self.delete_queries.append(query)
        return _DeleteResult(self._deleted)


class _FakeDB:
    def __init__(self, collection_name: str, collection: _FakeCollection):
        self._collections = {collection_name: collection}

    def __getitem__(self, name: str):
        return self._collections[name]


class _FakeHKCacheService:
    """模拟 HKCacheService 供路由测试使用"""
    def __init__(self):
        self.calls = []

    async def get_stock_info(self, symbol: str):
        self.calls.append(("get_stock_info", symbol))
        return {"symbol": symbol, "name": "Tencent"}

    async def refresh_cache(self, symbol: str):
        self.calls.append(("refresh_cache", symbol))
        return {"symbol": symbol, "name": "Tencent", "refreshed": True}

    async def warm_stock_with_quotes(self, stock_code: str, force: bool = False):
        self.calls.append(("warm_stock_with_quotes", stock_code, force))
        return {"info_success": True, "quotes_count": 30, "source": "akshare"}

    async def get_cache_stats(self):
        return {"market": "HK", "cached_symbols": 2}

    async def clear_expired_cache(self):
        self.calls.append(("clear_expired_cache", None))
        return {"market": "HK", "deleted_count": 3}


class _FakeUSCacheService:
    """模拟 USCacheService 供路由测试使用"""
    def __init__(self):
        self.calls = []

    async def get_stock_info(self, symbol: str):
        self.calls.append(("get_stock_info", symbol))
        return {"symbol": symbol, "name": "Apple"}

    async def refresh_cache(self, symbol: str):
        self.calls.append(("refresh_cache", symbol))
        return {"symbol": symbol, "name": "Apple", "refreshed": True}

    async def get_cache_stats(self):
        return {"market": "US", "cached_symbols": 5}

    async def clear_expired_cache(self):
        self.calls.append(("clear_expired_cache", None))
        return {"market": "US", "deleted_count": 4}


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


@pytest_asyncio.fixture
async def hk_client():
    from app.routers.sync.hk_sync import router

    app = _create_router_app(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest_asyncio.fixture
async def us_client():
    from app.routers.sync.us_sync import router

    app = _create_router_app(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.asyncio
async def test_hk_cache_service_stats_and_clear(monkeypatch):
    from app.worker.hk.hk_cache_service import HKCacheService

    collection_name = "stock_basic_info_hk"
    fake_collection = _FakeCollection(
        symbols=["00700", "00005"],
        codes=["00700"],
        total=3,
        valid=2,
        latest_doc={"symbol": "00700", "updated_at": "2026-05-17T11:00:00"},
        deleted=1,
    )
    fake_db = _FakeDB(collection_name, fake_collection)

    monkeypatch.setattr("app.worker.hk.hk_cache_service.get_mongo_db", lambda: fake_db)
    monkeypatch.setattr("app.worker.hk.hk_cache_service.get_enabled_sources", lambda m: ["yfinance"])

    service = HKCacheService()

    stats = await service.get_cache_stats()
    cleared = await service.clear_expired_cache()

    assert stats["cached_symbols"] == 2
    assert stats["total_documents"] == 3
    assert stats["valid_documents"] == 2
    assert stats["expired_documents"] == 1
    assert stats["latest_symbol"] == "00700"
    assert cleared["deleted_count"] == 1
    assert fake_collection.delete_queries


@pytest.mark.asyncio
async def test_us_cache_service_stats_and_clear(monkeypatch):
    from app.worker.us.us_cache_service import USCacheService

    collection_name = "stock_basic_info_us"
    fake_collection = _FakeCollection(
        symbols=["AAPL", "MSFT"],
        codes=["AAPL"],
        total=4,
        valid=3,
        latest_doc={"code": "MSFT", "updated_at": "2026-05-17T11:00:00"},
        deleted=2,
    )
    fake_db = _FakeDB(collection_name, fake_collection)

    monkeypatch.setattr("app.worker.us.us_cache_service.get_mongo_db", lambda: fake_db)
    monkeypatch.setattr("app.worker.us.us_cache_service.get_enabled_sources", lambda m: ["yfinance"])

    service = USCacheService()

    stats = await service.get_cache_stats()
    cleared = await service.clear_expired_cache()

    assert stats["cached_symbols"] == 2
    assert stats["total_documents"] == 4
    assert stats["valid_documents"] == 3
    assert stats["expired_documents"] == 1
    assert stats["latest_symbol"] == "MSFT"
    assert cleared["deleted_count"] == 2
    assert fake_collection.delete_queries


@pytest.mark.asyncio
async def test_hk_warm_route_respects_force_flag(monkeypatch, hk_client):
    import app.worker.hk as hk_worker

    fake_service = _FakeHKCacheService()
    monkeypatch.setattr(hk_worker, "get_hk_cache_service", lambda: fake_service)

    normal_resp = await hk_client.post("/api/sync/hk/cache/warm", json={"symbol": "00700", "force": False})
    force_resp = await hk_client.post("/api/sync/hk/cache/warm", json={"symbol": "00700", "force": True})

    assert normal_resp.status_code == 200
    assert force_resp.status_code == 200
    assert ("warm_stock_with_quotes", "00700", False) in fake_service.calls
    assert ("warm_stock_with_quotes", "00700", True) in fake_service.calls
    assert normal_resp.json()["success"] is True
    assert force_resp.json()["success"] is True


@pytest.mark.asyncio
async def test_us_clear_route_executes_cleanup(monkeypatch, us_client):
    import app.worker.us as us_worker

    fake_service = _FakeUSCacheService()
    monkeypatch.setattr(us_worker, "get_us_cache_service", lambda: fake_service)

    response = await us_client.delete("/api/sync/us/cache")

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["deleted_count"] == 4
    assert ("clear_expired_cache", None) in fake_service.calls
