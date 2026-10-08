"""Real MongoDB + real JWT/ASGI routes; GET never generates recommendations."""
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.routers.screening import router
from app.services.auth_service import AuthService
from app.services.user_service import user_service
from app.utils.time_utils import now_utc

pytestmark = pytest.mark.requires_db


async def test_daily_http_distinguishes_missing_generation_and_preserves_data(real_mongo_db):
    assert "test" in settings.MONGO_DB.lower() or "validation" in settings.MONGO_DB.lower()
    suffix = uuid4().hex
    username = "screening_http_" + suffix
    strategy_id = "screening_http_" + suffix
    original = user_service.db
    user_service.set_database(real_mongo_db)
    application = FastAPI()
    application.include_router(router)
    await real_mongo_db.users.insert_one({
        "username": username, "email": username + "@example.com",
        "hashed_password": user_service.hash_password(uuid4().hex),
        "is_admin": False, "is_active": True, "created_at": now_utc(),
        "preferences": {},
    })
    token = AuthService.create_access_token(sub=username)
    query = {"strategy_id": strategy_id}
    try:
        async with AsyncClient(transport=ASGITransport(app=application), base_url="http://testserver") as client:
            denied = await client.get("/api/screening/daily", params=query)
            assert denied.status_code in (401, 403)
            client.headers["Authorization"] = "Bearer " + token
            before = await real_mongo_db.screening_recommendations.count_documents({})
            response = await client.get("/api/screening/daily", params=query)
            assert response.status_code == 200
            body = response.json()["data"]
            assert body["status"] in ("no_factor_data", "not_generated")
            assert body["strategies"] == [] and body["trade_date"] is None
            assert await real_mongo_db.screening_recommendations.count_documents({}) == before
            assert "is_stale" in body and "expected_trade_date" in body

            # A genuine zero-match snapshot is not the same as never generated.
            document = {"strategy_id": strategy_id, "trade_date": "2026-09-11",
                        "strategy_name": "HTTP integration", "style": "short_term",
                        "total": 0, "items": [], "insight_status": "none"}
            result = await real_mongo_db.screening_recommendations.insert_one(document)
            saved = await real_mongo_db.screening_recommendations.find_one({"_id": result.inserted_id})
            for _ in range(2):
                response = await client.get("/api/screening/daily", params=query)
                assert response.status_code == 200
                data = response.json()["data"]
                assert data["status"] == "ready"
                assert len(data["strategies"]) == 1
                assert data["strategies"][0]["items"] == []
                assert data["strategies"][0]["data_quality"]["status"] == "unknown"
            assert await real_mongo_db.screening_recommendations.find_one({"_id": result.inserted_id}) == saved
            assert await real_mongo_db.screening_insights.count_documents({"user_id": username}) == 0
    finally:
        await real_mongo_db.users.delete_many({"username": username})
        await real_mongo_db.screening_recommendations.delete_many({"strategy_id": strategy_id})
        user_service.set_database(original)
