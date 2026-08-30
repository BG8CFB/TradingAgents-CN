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


def test_default_selected_roundtrip(tmp_path):
    """default_selected：true/false 落盘保留，缺省（None）不落盘"""
    on = _make_mode(default_selected=True)
    on_dict = on.model_dump(exclude_none=True)
    assert on_dict["default_selected"] is True

    config_path = tmp_path / "phase1_agents_config.yaml"
    _dump_modes(config_path, [on_dict])
    loaded = _load_modes(config_path)
    assert loaded[0]["default_selected"] is True

    off = _make_mode(default_selected=False)
    assert off.model_dump(exclude_none=True)["default_selected"] is False

    unset = _make_mode()
    assert "default_selected" not in unset.model_dump(exclude_none=True)


def test_phase1_config_default_selected_set():
    """实际 phase1 配置：5 个短线分析师默认选中，基本面不默认选中（短线工作流）"""
    from pathlib import Path

    from app.routers.agent_configs import CONFIG_DIR, _load_modes

    config_path = CONFIG_DIR / "phase1_agents_config.yaml"
    if not Path(config_path).exists():
        # AGENT_CONFIG_DIR 指向外部目录时跳过仓库内置配置断言
        import os

        if os.environ.get("AGENT_CONFIG_DIR"):
            return
        raise AssertionError(f"phase1 配置不存在: {config_path}")

    modes = {m["slug"]: m for m in _load_modes(config_path)}
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
