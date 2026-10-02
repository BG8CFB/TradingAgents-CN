"""agents 路由：库级单条 CRUD / 内置保护 / 引用计数 / fork（真实路由 + 真实 Mongo）。

覆盖设计文档 §7 API 表 agents 半区：
- 列表（builtin 标记 + 引用计数聚合）、新建（409 撞现存/内置）、详情 404
- 内置 403（PUT/DELETE）、phase 不可改、slug 一致性
- 删除保护：被工作流 nodes 段引用 → 409 + referenced_by；未引用用户条目物理删除
- fork 复制私有副本（内置定制的唯一路径）
"""

import copy

import pytest

from app.engine.orchestrator.workflow import store


@pytest.fixture
def agent_env(real_mongo_db):
    """清用户条目后重注种子（agent/workflow 双集合），用例后同样复位。"""
    from app.engine.orchestrator.workflow.loader import clear_workflow_cache
    from app.engine.orchestrator.workflow.seeder import sync_agent_specs, sync_workflow_specs

    def _reset():
        store._db()[store.AGENT_SPECS_COLLECTION].delete_many({})
        store._db()[store.WORKFLOW_SPECS_COLLECTION].delete_many({"builtin": False})
        store.invalidate_store_cache()
        sync_agent_specs()
        sync_workflow_specs()
        clear_workflow_cache()

    _reset()
    yield store
    _reset()


def _agent_payload(**overrides) -> dict:
    base = {
        "phase": 2,
        "slug": "my-debater",
        "name": "自定义辩手",
        "roleDefinition": "你是自定义辩手",
        "template_inputs": [{"slot": "analyst_reports", "required_sources": []}],
    }
    base.update(overrides)
    return base


def _referencing_workflow(agent_slug: str) -> dict:
    """内置工作流副本：多头辩手位换成自定义 agent（nodes 段 + sides 引用同步）"""
    spec = copy.deepcopy(store._seed_workflow_docs()[0]["spec"])
    spec["slug"] = f"flow-using-{agent_slug}"
    spec["name"] = "引用自定义智能体的工作流"
    spec["builtin"] = False
    bull = next(n for n in spec["nodes"] if n["slug"] == "bull-researcher")
    bull["slug"] = agent_slug
    bull["memory"] = None
    debate = next(s for s in spec["stages"] if s["id"] == "research_debate")
    debate["sides"] = [agent_slug, "bear-researcher"]
    debate["report_view"] = "generic"
    return spec


async def _create_agent(authed_client, **overrides) -> dict:
    resp = await authed_client.post("/api/agents", json=_agent_payload(**overrides))
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["spec"]


# ── 列表与鉴权 ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_requires_auth(client):
    resp = await client.get("/api/agents")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_builtin_flag_and_reference_counts(authed_client, agent_env):
    resp = await authed_client.get("/api/agents")
    assert resp.status_code == 200
    items = {a["slug"]: a for a in resp.json()["data"]["agents"]}
    # 内置判定 = 种子集（非文档 builtin 字段口径）
    assert items["bull-researcher"]["builtin"] is True
    assert items["bull-researcher"]["phase"] == 2
    # default-4stage 的 nodes 段引用 bull-researcher → 引用计数命中
    assert items["bull-researcher"]["referenced_by"] == ["default-4stage"]
    # phase1 pool 分析师不进 nodes 段，无结构性引用
    assert items["market-analyst"]["referenced_by"] == []


@pytest.mark.asyncio
async def test_list_phase_filter(authed_client, agent_env):
    resp = await authed_client.get("/api/agents?phase=1")
    items = resp.json()["data"]["agents"]
    assert items and all(a["phase"] == 1 for a in items)


# ── 新建 / 详情 ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_then_conflict(authed_client, agent_env):
    created = await _create_agent(authed_client)
    assert created["slug"] == "my-debater"
    assert agent_env.get_agent_doc("my-debater")["builtin"] is False

    resp = await authed_client.post("/api/agents", json=_agent_payload())
    assert resp.status_code == 409
    # 与内置同 slug 新建同样 409（设计 §8：不存在用户定义覆盖内置的歧义）
    resp = await authed_client.post("/api/agents", json=_agent_payload(slug="bull-researcher"))
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_create_blank_fields_rejected(authed_client, agent_env):
    resp = await authed_client.post("/api/agents", json=_agent_payload(roleDefinition="  "))
    assert resp.status_code == 422
    assert agent_env.get_agent_doc("my-debater") is None


@pytest.mark.asyncio
async def test_get_detail_and_404(authed_client, agent_env):
    await _create_agent(authed_client)
    resp = await authed_client.get("/api/agents/my-debater")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["builtin"] is False
    assert data["referenced_by"] == []

    resp = await authed_client.get("/api/agents/no-such-agent")
    assert resp.status_code == 404


# ── 更新 ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_builtin_403(authed_client, agent_env):
    payload = _agent_payload(slug="bull-researcher")
    resp = await authed_client.put("/api/agents/bull-researcher", json=payload)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_update_custom_ok_and_guards(authed_client, agent_env):
    await _create_agent(authed_client)
    resp = await authed_client.put("/api/agents/my-debater", json=_agent_payload(roleDefinition="改后的提示词"))
    assert resp.status_code == 200
    assert agent_env.get_agent_spec("my-debater")["roleDefinition"] == "改后的提示词"

    resp = await authed_client.put("/api/agents/my-debater", json=_agent_payload(slug="other"))
    assert resp.status_code == 400
    resp = await authed_client.put("/api/agents/my-debater", json=_agent_payload(phase=3))
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_update_missing_404(authed_client, agent_env):
    resp = await authed_client.put("/api/agents/ghost-agent", json=_agent_payload(slug="ghost-agent"))
    assert resp.status_code == 404


# ── 删除 ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_builtin_403(authed_client, agent_env):
    resp = await authed_client.delete("/api/agents/bull-researcher")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_referenced_409(authed_client, agent_env):
    """用户 agent 被自定义工作流 nodes 引用 → 409 + 引用列表"""
    await _create_agent(authed_client)
    resp = await authed_client.post("/api/workflows", json=_referencing_workflow("my-debater"))
    assert resp.status_code == 200, resp.text

    resp = await authed_client.delete("/api/agents/my-debater")
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["referenced_by"] == ["flow-using-my-debater"]
    assert agent_env.get_agent_doc("my-debater") is not None


@pytest.mark.asyncio
async def test_delete_unreferenced_custom_physical(authed_client, agent_env):
    await _create_agent(authed_client)
    resp = await authed_client.delete("/api/agents/my-debater")
    assert resp.status_code == 200
    assert resp.json()["data"]["action"] == "deleted"
    assert agent_env.get_agent_doc("my-debater") is None  # 用户条目物理删除


# ── fork ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fork_builtin_copies_spec(authed_client, agent_env):
    resp = await authed_client.post("/api/agents/bull-researcher/fork", json={"new_slug": "my-bull"})
    assert resp.status_code == 200
    spec = resp.json()["data"]["spec"]
    assert spec["slug"] == "my-bull"
    assert "（副本）" in spec["name"]
    assert spec["roleDefinition"] == agent_env.get_agent_spec("bull-researcher")["roleDefinition"]
    assert agent_env.get_agent_doc("my-bull")["builtin"] is False
    # fork 不影响源条目
    assert agent_env.get_agent_doc("bull-researcher") is not None


@pytest.mark.asyncio
async def test_fork_guards(authed_client, agent_env):
    resp = await authed_client.post("/api/agents/bull-researcher/fork", json={"new_slug": "bull-researcher"})
    assert resp.status_code == 400

    resp = await authed_client.post("/api/agents/bull-researcher/fork", json={"new_slug": "bear-researcher"})
    assert resp.status_code == 409

    resp = await authed_client.post("/api/agents/ghost-agent/fork", json={"new_slug": "x"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_forked_agent_usable_in_workflow(authed_client, agent_env):
    """fork 产物可被自定义工作流引用（接入 P4-a N 方辩论链路）"""
    await authed_client.post("/api/agents/bull-researcher/fork", json={"new_slug": "my-bull"})
    resp = await authed_client.post("/api/workflows", json=_referencing_workflow("my-bull"))
    assert resp.status_code == 200, resp.text

    items = {a["slug"]: a for a in (await authed_client.get("/api/agents")).json()["data"]["agents"]}
    assert items["my-bull"]["referenced_by"] == ["flow-using-my-bull"]
