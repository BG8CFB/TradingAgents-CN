"""workflows 路由：CRUD / 内置保护 / 校验 / 设默认（真实路由 + 真实 Mongo，无 mock）。

覆盖设计文档 §7 API 表的 workflows 半区：
- 列表（内置 + 校验状态 + 默认标记）、新建（409 / 校验 400）、详情 404
- 内置 403（PUT/DELETE）、自定义软删除、slug 一致性
- validate（编辑器保存前）、validate-run（裁剪可行性 + required fail-fast）
- 设默认（system_configs 持久化 + 删除默认回落）
"""

import copy

import pytest

from app.engine.orchestrator.workflow import store
from app.engine.orchestrator.workflow.loader import default_workflow_slug

BUILTIN_SLUG = "default-4stage"
PHASE1_SLUGS = (
    "financial-news-analyst",
    "china-market-analyst",
    "market-analyst",
    "social-media-analyst",
    "fundamentals-analyst",
    "short-term-capital-analyst",
)


@pytest.fixture
def workflow_env(real_mongo_db):
    """种子内置工作流 + 清默认设置残留（agents/workflows 双种子对齐生产 seeder）。"""
    from app.engine.orchestrator.workflow.loader import clear_workflow_cache
    from app.engine.orchestrator.workflow.seeder import sync_agent_specs, sync_workflow_specs

    def _purge_test_artifacts():
        """清自定义工作流与默认设置残留（builtin 文档归 seeder 管理）"""
        store._db()[store.WORKFLOW_SPECS_COLLECTION].delete_many({"builtin": {"$ne": True}})
        store.clear_default_workflow_slug()
        store.invalidate_store_cache()

    _purge_test_artifacts()
    sync_agent_specs()
    sync_workflow_specs()
    clear_workflow_cache()
    yield store
    _purge_test_artifacts()
    clear_workflow_cache()


def _custom_spec(slug: str = "my-custom-flow") -> dict:
    """内置种子 spec 的自定义副本（slug/name 换新、builtin 翻 false）"""
    seed = store._seed_workflow_docs()[0]["spec"]
    spec = copy.deepcopy(seed)
    spec["slug"] = slug
    spec["name"] = "我的自定义工作流"
    spec["builtin"] = False
    return spec


async def _create_custom(authed_client, slug: str = "my-custom-flow") -> dict:
    resp = await authed_client.post("/api/workflows", json=_custom_spec(slug))
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True
    return resp.json()["data"]["workflow"]


# ── 列表与鉴权 ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_requires_auth(client):
    resp = await client.get("/api/workflows")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_includes_builtin_with_default_flag(authed_client, workflow_env):
    resp = await authed_client.get("/api/workflows")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    items = {w["slug"]: w for w in body["data"]["workflows"]}
    assert BUILTIN_SLUG in items
    builtin = items[BUILTIN_SLUG]
    assert builtin["builtin"] is True
    assert builtin["valid"] is True
    assert builtin["is_default"] is True  # 未显式设置时回落内置默认
    assert body["data"]["default_slug"] == BUILTIN_SLUG
    assert [s["id"] for s in builtin["stages"]] == [
        "analysts",
        "research_debate",
        "trader",
        "risk_debate",
        "summary",
    ]


@pytest.mark.asyncio
async def test_list_marks_broken_spec_invalid(authed_client, workflow_env):
    """DB 中被改坏的 spec 不阻断列表，标 valid=false + 错误信息"""
    coll = workflow_env._db()[workflow_env.WORKFLOW_SPECS_COLLECTION]
    coll.insert_one(
        {
            "_id": "broken-flow",
            "builtin": False,
            "deleted": False,
            "spec": {"slug": "broken-flow", "name": "坏工作流"},  # 缺 stages/terminal
        }
    )
    workflow_env.invalidate_store_cache()

    resp = await authed_client.get("/api/workflows")
    items = {w["slug"]: w for w in resp.json()["data"]["workflows"]}
    broken = items["broken-flow"]
    assert broken["valid"] is False
    assert broken["validation_errors"]
    assert broken["stages"] == []


# ── 新建 ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_custom_then_conflict(authed_client, workflow_env):
    created = await _create_custom(authed_client)
    assert created["slug"] == "my-custom-flow"
    assert created["builtin"] is False

    resp = await authed_client.post("/api/workflows", json=_custom_spec())
    assert resp.status_code == 409

    doc = workflow_env.get_workflow_doc("my-custom-flow")
    assert doc is not None and doc["builtin"] is False


@pytest.mark.asyncio
async def test_create_forces_builtin_false(authed_client, workflow_env):
    """payload 声称 builtin=true 也不能伪装内置（内置由 seeder 独占管理）"""
    payload = _custom_spec("imposter-flow")
    payload["builtin"] = True
    resp = await authed_client.post("/api/workflows", json=payload)
    assert resp.status_code == 200
    assert workflow_env.get_workflow_doc("imposter-flow")["builtin"] is False


@pytest.mark.asyncio
async def test_create_invalid_spec_returns_field_errors(authed_client, workflow_env):
    payload = _custom_spec("bad-flow")
    del payload["terminal"]
    payload.pop("stages")
    resp = await authed_client.post("/api/workflows", json=payload)
    assert resp.status_code == 400
    errors = resp.json()["detail"]["errors"]
    assert errors and any("terminal" in e or "stages" in e for e in errors)
    assert workflow_env.get_workflow_doc("bad-flow") is None


@pytest.mark.asyncio
async def test_create_builtin_slug_conflict(authed_client, workflow_env):
    resp = await authed_client.post("/api/workflows", json=_custom_spec(BUILTIN_SLUG))
    assert resp.status_code == 409


# ── 详情 / 更新 / 删除 ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_detail_and_404(authed_client, workflow_env):
    resp = await authed_client.get(f"/api/workflows/{BUILTIN_SLUG}")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["builtin"] is True
    assert data["workflow"]["slug"] == BUILTIN_SLUG
    assert data["workflow"]["terminal"]["decision_field"] == "final_trade_decision"

    resp = await authed_client.get("/api/workflows/no-such-flow")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_builtin_403(authed_client, workflow_env):
    resp = await authed_client.put(f"/api/workflows/{BUILTIN_SLUG}", json=_custom_spec(BUILTIN_SLUG))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_update_custom_and_slug_mismatch(authed_client, workflow_env):
    await _create_custom(authed_client)
    payload = _custom_spec("my-custom-flow")
    payload["description"] = "改了描述"
    resp = await authed_client.put("/api/workflows/my-custom-flow", json=payload)
    assert resp.status_code == 200
    assert workflow_env.get_workflow_spec("my-custom-flow")["description"] == "改了描述"

    mismatch = _custom_spec("another-slug")
    resp = await authed_client.put("/api/workflows/my-custom-flow", json=mismatch)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_delete_builtin_403(authed_client, workflow_env):
    resp = await authed_client.delete(f"/api/workflows/{BUILTIN_SLUG}")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_custom_is_soft(authed_client, workflow_env):
    """软删除：列表/消费视图消失，文档保留（历史任务回放 + 同名重建可复活）"""
    await _create_custom(authed_client)
    resp = await authed_client.delete("/api/workflows/my-custom-flow")
    assert resp.status_code == 200

    assert workflow_env.get_workflow_spec("my-custom-flow") is None
    doc = workflow_env.get_workflow_doc("my-custom-flow")
    assert doc is not None and doc.get("deleted") is True

    # tombstone 不阻断同名重建（用户显式重建 ≠ seed 复活）
    resp = await authed_client.post("/api/workflows", json=_custom_spec())
    assert resp.status_code == 200
    assert workflow_env.get_workflow_spec("my-custom-flow") is not None


# ── 设默认 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_default_persists_and_reflects(authed_client, workflow_env):
    await _create_custom(authed_client)
    resp = await authed_client.post("/api/workflows/my-custom-flow/default")
    assert resp.status_code == 200
    assert resp.json()["data"]["default_slug"] == "my-custom-flow"

    # system_configs 持久化 + 生效解析同口径
    assert workflow_env.get_default_workflow_slug() == "my-custom-flow"
    assert default_workflow_slug() == "my-custom-flow"

    items = {w["slug"]: w for w in (await authed_client.get("/api/workflows")).json()["data"]["workflows"]}
    assert items["my-custom-flow"]["is_default"] is True
    assert items[BUILTIN_SLUG]["is_default"] is False


@pytest.mark.asyncio
async def test_set_default_404_and_disabled_400(authed_client, workflow_env):
    resp = await authed_client.post("/api/workflows/no-such-flow/default")
    assert resp.status_code == 404

    payload = _custom_spec("disabled-flow")
    payload["enabled"] = False
    await authed_client.post("/api/workflows", json=payload)
    resp = await authed_client.post("/api/workflows/disabled-flow/default")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_delete_default_falls_back_to_builtin(authed_client, workflow_env):
    await _create_custom(authed_client)
    await authed_client.post("/api/workflows/my-custom-flow/default")
    resp = await authed_client.delete("/api/workflows/my-custom-flow")
    assert resp.status_code == 200
    assert workflow_env.get_default_workflow_slug() is None
    assert default_workflow_slug() == BUILTIN_SLUG


# ── validate / validate-run ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_ok_and_errors(authed_client, workflow_env):
    resp = await authed_client.post("/api/workflows/validate", json=_custom_spec())
    assert resp.status_code == 200
    assert resp.json()["data"] == {"valid": True, "errors": []}

    broken = _custom_spec("broken-flow")
    broken["stages"][1].pop("judge")  # 辩论组缺 judge
    resp = await authed_client.post("/api/workflows/validate", json=broken)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["valid"] is False
    assert data["errors"]


@pytest.mark.asyncio
async def test_validate_run_full_selection_ok(authed_client, workflow_env):
    resp = await authed_client.post(
        "/api/workflows/validate-run",
        json={"workflow_slug": BUILTIN_SLUG, "selected_nodes": list(PHASE1_SLUGS)},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["valid"] is True, data["errors"]
    assert data["plan"]["total_units"] > 0
    stage_ids = [s["stage_id"] for s in data["plan"]["stages"]]
    assert stage_ids == ["analysts", "research_debate", "trader", "risk_debate", "summary"]


@pytest.mark.asyncio
async def test_validate_run_required_conflict(authed_client, workflow_env):
    """裁掉 market-analyst → bull-researcher/trader 的 required market_report 缺失"""
    selected = [s for s in PHASE1_SLUGS if s != "market-analyst"]
    resp = await authed_client.post(
        "/api/workflows/validate-run",
        json={"workflow_slug": BUILTIN_SLUG, "selected_nodes": selected},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["valid"] is False
    assert any("market_report" in e for e in data["errors"])


@pytest.mark.asyncio
async def test_validate_run_unknown_workflow(authed_client, workflow_env):
    resp = await authed_client.post("/api/workflows/validate-run", json={"workflow_slug": "no-such-flow"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["valid"] is False
    assert data["errors"]
