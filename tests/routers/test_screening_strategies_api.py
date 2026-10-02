"""/api/screening/strategies 与 /run 策略路径测试。

- /strategies 端点：HTTP 端到端（SimulatedMongoDB + 真实 JWT 鉴权路径，业务数据 YAML 驱动）
- /run 策略分支：真库直调路由函数（覆盖条件转换 + 白名单过滤 + success 信封）
"""
import pytest

pytestmark = pytest.mark.requires_db

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name
from app.data.storage.mongo.repositories.factor_scores_repo import FactorScoresRepo
from app.routers.screening import ScreeningRequest, run_screening


async def _seed_strategy_rows():
    """3 只股 × 同一 trade_date：volume_breakout 命中 2 只，其中银行 1 只。"""
    db = get_motor_db()
    coll = db[get_collection_name("factor_scores", "CN")]
    await coll.delete_many({"symbol": {"$regex": "^TESTR"}})
    await FactorScoresRepo().upsert_many([
        {"symbol": "TESTR001", "trade_date": "2026-09-11", "name": "甲", "industry": "银行",
         "bias_ma20": 3.0, "turnover_amp": 2.0, "macd_golden_days": 3, "main_inflow_5d": 1e8,
         "score_short_term": 95.0, "score_balanced": 80.0, "score_value": 40.0, "ret_5d": 5.0},
        {"symbol": "TESTR002", "trade_date": "2026-09-11", "name": "乙", "industry": "医药",
         "bias_ma20": 1.0, "turnover_amp": 1.6, "macd_golden_days": 2, "main_inflow_5d": 5e7,
         "score_short_term": 88.0, "score_balanced": 70.0, "score_value": 50.0, "ret_5d": 2.0},
        {"symbol": "TESTR003", "trade_date": "2026-09-11", "name": "丙", "industry": "电子",
         "bias_ma20": -1.0, "turnover_amp": 3.0, "macd_golden_days": 4, "main_inflow_5d": 2e8,
         "score_short_term": 99.0, "score_balanced": 90.0, "score_value": 60.0, "ret_5d": 8.0},
    ], market="CN")


async def _cleanup_strategy_rows():
    db = get_motor_db()
    await db[get_collection_name("factor_scores", "CN")].delete_many(
        {"symbol": {"$regex": "^TESTR"}})


async def test_strategies_endpoint(inject_sim_db):
    """GET /api/screening/strategies：真实 JWT 鉴权 + success 信封 + 6 模板。"""
    from app.services.user_service import user_service
    from app.services.auth_service import AuthService
    from app.utils.passwords import hash_password
    from app.utils.time_utils import now_utc

    original_db = user_service.db
    user_service.set_database(inject_sim_db)
    await inject_sim_db.users.insert_one({
        "_id": "507f1f77bcf86cd7994300aa",
        "username": "screening_routes_user",
        "email": "screening_routes@test.com",
        "hashed_password": hash_password("Test@1234"),
        "is_admin": False, "is_active": True,
        "created_at": now_utc(), "preferences": {},
    })
    token = AuthService.create_access_token(sub="screening_routes_user")

    app = FastAPI()
    from app.routers.screening import router
    app.include_router(router)
    try:
        async with AsyncClient(transport=ASGITransport(app=app),
                               base_url="http://testserver") as ac:
            resp = await ac.get("/api/screening/strategies",
                                headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        strategies = body["data"]["strategies"]
        assert len(strategies) == 6
        assert any(s["is_default"] for s in strategies)
    finally:
        user_service.set_database(original_db)
        await inject_sim_db.users.delete_many(
            {"username": "screening_routes_user"})


async def test_run_strategy_branch_with_extra_condition(real_mongo_db):
    """POST /run {strategy_id}：叠加 industry 条件 → 1 只 + 信封字段齐全。"""
    await _seed_strategy_rows()
    req = ScreeningRequest(strategy_id="volume_breakout", conditions={
        "children": [{"field": "industry", "op": "eq", "value": "银行"}]})
    resp = await run_screening(req, user={"username": "t"})
    assert resp["success"] is True
    data = resp["data"]
    assert data["total"] == 1
    assert data["items"][0]["symbol"] == "TESTR001"
    assert data["strategy"] == "volume_breakout"
    assert data["style"] == "short_term"
    assert data["as_of"] == "2026-09-11"
    await _cleanup_strategy_rows()


async def test_run_strategy_branch_ignores_non_whitelist_fields(real_mongo_db):
    """叠加条件 field 不在因子白名单（如 close）→ 被忽略，结果不变。"""
    await _seed_strategy_rows()
    req = ScreeningRequest(strategy_id="volume_breakout", conditions={
        "children": [{"field": "close", "op": "eq", "value": 999}]})
    resp = await run_screening(req, user={"username": "t"})
    assert resp["success"] is True
    # close 非白名单字段被剔除 → 无叠加条件 → 命中 2 只
    assert resp["data"]["total"] == 2
    await _cleanup_strategy_rows()


async def test_run_strategy_empty_factor_data_full_shape(real_mongo_db):
    """factor_scores 全空（L0 尚未批算）→ 200 + 完整响应形状（回归：曾漏 style 键致 500）。"""
    db = get_motor_db()
    coll = db[get_collection_name("factor_scores", "CN")]
    await coll.delete_many({})  # 测试库隔离，清空后不恢复（其他用例自带种子）
    req = ScreeningRequest(strategy_id="volume_breakout", conditions={})
    resp = await run_screening(req, user={"username": "t"})
    assert resp["success"] is True
    data = resp["data"]
    assert data["total"] == 0
    assert data["items"] == []
    assert data["as_of"] is None
    assert data["strategy"] == "volume_breakout"
    assert data["style"] == "short_term"
