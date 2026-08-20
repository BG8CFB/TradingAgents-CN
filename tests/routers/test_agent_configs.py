"""agent-configs 路由：新配置模型校验 + YAML 落盘往返（真实 I/O，无 mock）"""

import yaml

from app.routers.agent_configs import (
    AgentConfigPayload,
    AgentMode,
    _dump_modes,
    _load_modes,
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


def test_yaml_roundtrip_preserves_new_fields(tmp_path):
    mode = _make_mode(mcp_tools=["fetch"], skills=None)
    mode_dict = mode.model_dump(exclude_none=True)
    mode_dict["description"] = mode.slug

    config_path = tmp_path / "phase1_agents_config.yaml"
    _dump_modes(config_path, [mode_dict])

    loaded = _load_modes(config_path)
    assert len(loaded) == 1
    assert loaded[0]["data_tools"] == ["daily_quotes", "news"]
    assert loaded[0]["mcp_tools"] == ["fetch"]
    assert "skills" not in loaded[0]

    # 语义层再校验：yaml 原生往返一致
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert raw["customModes"][0]["slug"] == "test-analyst"
