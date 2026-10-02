"""registry 路由：显示名单单一来源（真实路由 + 鉴权依赖，无 mock）"""

import pytest


@pytest.mark.asyncio
async def test_display_names_requires_auth(client):
    """无 Authorization 时 get_current_user 真实拒绝（401）"""
    resp = await client.get("/api/registry/display-names")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_display_names_wraps_success_data(authed_client):
    """响应包 success+data（前端 store 契约：裸 dict 会被静默丢弃）"""
    resp = await authed_client.get("/api/registry/display-names")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert isinstance(data, dict) and data


@pytest.mark.asyncio
async def test_display_names_covers_alias_and_key_classes(authed_client):
    """键集合覆盖前端历史别名表与四类键形态（slug/base/base_report/base_analyst）"""
    resp = await authed_client.get("/api/registry/display-names")
    data = resp.json()["data"]
    # 前端旧 REPORT_KEY_SLUG_ALIAS 六别名（含补齐的 risk_manager_decision）
    for alias in (
        "trader_investment_plan",
        "investment_plan",
        "final_trade_decision",
        "research_team_decision",
        "risk_management_decision",
        "risk_manager_decision",
    ):
        assert data.get(alias), f"别名键缺失: {alias}"
    # 四类键形态（trader / bull-researcher 各代表非 -analyst 与 -analyst 后缀形态）
    for key in (
        "trader",
        "trader_report",
        "trader_analyst",
        "bull-researcher",
        "bull_researcher",
        "bull_researcher_report",
    ):
        assert data.get(key), f"键缺失: {key}"


@pytest.mark.asyncio
async def test_display_names_matches_registry_singleton(authed_client):
    """下发数据与后端 registry 单一权威表逐项一致"""
    from app.engine.orchestrator.registry import all_display_keys

    resp = await authed_client.get("/api/registry/display-names")
    assert resp.json()["data"] == all_display_keys()
