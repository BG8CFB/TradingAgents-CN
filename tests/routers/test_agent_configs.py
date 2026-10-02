"""agent-configs 路由：新配置模型校验 + DB 落库往返（真实 I/O，无 mock）"""

import pytest

from app.routers.agent_configs import (
    AgentConfigPayload,
    AgentMode,
)


def _make_mode(**overrides) -> AgentMode:
    base = {
        "slug": "test-analyst",
        "name": "测试分析师",
        "roleDefinition": "你是测试分析师",
        "data_tools": ["daily_quotes", "news"],
    }
    base.update(overrides)
    return AgentMode(**base)


def test_mode_rejects_blank_required_fields():
    try:
        AgentMode(slug="", name="x", roleDefinition="y")
        raise AssertionError("空 slug 应被拒绝")
    except ValueError:
        pass


def test_tool_lists_dedup_and_empty_become_none():
    mode = _make_mode(
        data_tools=["news", "news", " "],
        mcp_tools=[],
        skills=["a.b", "a.b"],
    )
    assert mode.data_tools == ["news"]
    # 空列表语义 = 全部可用/不注入，统一归一化为 None
    assert mode.mcp_tools is None
    assert mode.skills == ["a.b"]


def test_payload_dump_strips_legacy_keys():
    payload = AgentConfigPayload(customModes=[_make_mode()])
    data = payload.customModes[0].model_dump(exclude_none=True)
    for key in ("whenToUse", "groups", "source", "initial_task", "tools"):
        assert key not in data
    assert data["data_tools"] == ["daily_quotes", "news"]


@pytest.fixture
def agent_specs_store(mongodb_available):
    """独占 agent_specs 集合：用例前清空，用例后清空（种子降级保底其他测试）。"""
    from app.engine.orchestrator.workflow import store

    store.invalidate_store_cache()
    store._db()[store.AGENT_SPECS_COLLECTION].delete_many({})
    store.invalidate_store_cache()
    yield store
    store._db()[store.AGENT_SPECS_COLLECTION].delete_many({})
    store.invalidate_store_cache()


def _dump_entries(store, mode_dicts):
    """走路由同款落库路径（replace_phase_agent_specs）"""
    store.replace_phase_agent_specs(1, mode_dicts)


def test_db_roundtrip_preserves_new_fields(agent_specs_store):
    store = agent_specs_store
    mode = _make_mode(mcp_tools=["fetch"], skills=None)
    mode_dict = mode.model_dump(exclude_none=True)
    mode_dict["description"] = mode.slug

    _dump_entries(store, [mode_dict])
    loaded = store.list_agent_specs(phase=1)
    assert len(loaded) == 1
    assert loaded[0]["data_tools"] == ["daily_quotes", "news"]
    assert loaded[0]["mcp_tools"] == ["fetch"]
    assert "skills" not in loaded[0]


def test_default_selected_roundtrip(agent_specs_store):
    """default_selected：true/false 落库保留，缺省（None）不落库"""
    store = agent_specs_store
    on = _make_mode(default_selected=True)
    on_dict = on.model_dump(exclude_none=True)
    assert on_dict["default_selected"] is True

    _dump_entries(store, [on_dict])
    loaded = store.list_agent_specs(phase=1)
    assert loaded[0]["default_selected"] is True

    off = _make_mode(default_selected=False)
    assert off.model_dump(exclude_none=True)["default_selected"] is False

    unset = _make_mode()
    assert "default_selected" not in unset.model_dump(exclude_none=True)


def test_phase1_default_selected_set():
    """phase1 智能体库：5 个短线分析师默认选中，基本面不默认选中（短线工作流）"""
    from app.engine.orchestrator.workflow import seeds

    modes = {e["spec"]["slug"]: e["spec"] for e in seeds.load_agent_seeds() if e["phase"] == 1}
    expected_on = {
        "market-analyst",
        "short-term-capital-analyst",
        "financial-news-analyst",
        "social-media-analyst",
        "china-market-analyst",
    }
    actual_on = {slug for slug, m in modes.items() if m.get("default_selected") is True}
    assert actual_on == expected_on
    assert modes["fundamentals-analyst"].get("default_selected") is not True
