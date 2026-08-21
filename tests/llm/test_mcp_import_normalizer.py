"""MCP 多格式导入归一化测试（真实解析路径，无 mock）"""


import pytest

from app.llm.mcp.management.import_normalizer import (
    ImportFormat,
    normalize_import,
    normalize_import_raw,
)


# ---------- 格式识别 ----------

def test_detect_claude_desktop_format():
    insight = normalize_import(
        {"mcpServers": {"fs": {"command": "npx", "args": ["-y", "server-fs"]}}}
    )
    assert insight.format == ImportFormat.CLAUDE_DESKTOP
    assert "fs" in insight.servers
    assert insight.servers["fs"]["type"] == "stdio"
    assert insight.servers["fs"]["command"] == "npx"


def test_detect_cline_format_and_drop_fields():
    insight = normalize_import(
        {
            "mcpServers": {
                "search": {
                    "command": "npx",
                    "args": ["-y", "server-search"],
                    "fromGalleryId": "cline.xxx",
                    "alwaysAllow": ["search"],
                    "autoApprove": ["search"],
                    "disabled": True,
                }
            }
        }
    )
    assert insight.format == ImportFormat.CLINE
    # disabled → _enabled=False
    assert insight.servers["search"]["_enabled"] is False
    # cline 特有字段被丢弃并回显 warning
    assert any("fromGalleryId" in w for w in insight.warnings)
    assert any("alwaysAllow" in w for w in insight.warnings)
    assert any("autoApprove" in w for w in insight.warnings)
    # 丢弃字段不落盘
    assert "fromGalleryId" not in insight.servers["search"]
    assert "alwaysAllow" not in insight.servers["search"]


def test_detect_kilo_format_sse_and_cwd():
    insight = normalize_import(
        {
            "mcpServers": {
                "old-remote": {
                    "type": "sse",
                    "url": "https://example.com/sse",
                    "cwd": "/tmp/work",
                }
            }
        }
    )
    assert insight.format == ImportFormat.KILO
    assert insight.servers["old-remote"]["type"] == "sse"
    assert insight.servers["old-remote"]["url"] == "https://example.com/sse"
    assert any("cwd" in w for w in insight.warnings)
    assert "cwd" not in insight.servers["old-remote"]


def test_detect_bare_server_and_autowrap():
    insight = normalize_import(
        {"command": "python", "args": ["-m", "my.mcp.server"]}
    )
    assert insight.format == ImportFormat.BARE_SERVER
    (name,) = insight.servers.keys()
    # python -m 场景取模块尾段命名
    assert name == "server"
    assert insight.servers[name]["type"] == "stdio"


def test_servers_variant_key_accepted():
    insight = normalize_import({"servers": {"a": {"command": "npx"}}})
    assert "a" in insight.servers


# ---------- 类型推导与环境变量 ----------

def test_type_inference_no_type_with_url():
    insight = normalize_import(
        {"mcpServers": {"remote": {"url": "https://example.com/mcp"}}}
    )
    assert insight.servers["remote"]["type"] == "streamable-http"


def test_env_placeholder_expansion(monkeypatch):
    monkeypatch.setenv("MCP_IMPORT_TEST_TOKEN", "abc123")
    insight = normalize_import(
        {"mcpServers": {"s": {"command": "npx", "env": {"TOKEN": "${MCP_IMPORT_TEST_TOKEN}"}}}}
    )
    assert insight.servers["s"]["env"]["TOKEN"] == "abc123"


# ---------- 错误收集（不阻断整体） ----------

def test_invalid_url_collected_not_blocking():
    insight = normalize_import(
        {
            "mcpServers": {
                "good": {"command": "npx", "args": ["-y", "ok"]},
                "bad": {"url": "ftp://not-http.example.com"},
            }
        }
    )
    assert "good" in insight.servers
    assert "bad" in insight.errors
    assert "http" in insight.errors["bad"] or "url" in insight.errors["bad"].lower()


def test_raw_json_parse_error_with_position():
    with pytest.raises(ValueError, match="JSON"):
        normalize_import_raw("{ not valid json")


def test_empty_servers_rejected():
    with pytest.raises(ValueError):
        normalize_import({"mcpServers": {}})


# ---------- 落盘 roundtrip（integration：真实文件 I/O） ----------

@pytest.mark.integration
def test_import_update_load_roundtrip(tmp_path, monkeypatch):
    from app.llm.mcp.management import config_store

    config_file = tmp_path / "mcp.json"
    monkeypatch.setattr(config_store, "DEFAULT_CONFIG_FILE", config_file)

    insight = normalize_import(
        {
            "mcpServers": {
                "imported": {
                    "command": "npx",
                    "args": ["-y", "server-x"],
                    "disabled": True,
                    "alwaysAllow": ["tool1"],
                }
            }
        }
    )
    merged = config_store.merge_servers({}, insight.servers, strict=True)
    config_store.write_mcp_config({"mcpServers": merged}, config_file)

    loaded = config_store.load_mcp_config(config_file)
    assert "imported" in loaded["mcpServers"]
    assert loaded["mcpServers"]["imported"]["command"] == "npx"
    assert loaded["mcpServers"]["imported"]["_enabled"] is False
