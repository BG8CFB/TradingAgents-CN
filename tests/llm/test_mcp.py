"""MCP 测试：真实 stdio server 进程（官方 mcp SDK FastMCP），发现→包装→调用→错误回传（禁止 mock）"""

import sys
from pathlib import Path

import pytest

from app.llm import create_client
from app.llm.config import load_config
from app.llm.mcp import MCPManager, MCPServerConfig, discover_mcp_tools, mcp_tool_name
from app.llm.mcp.config import expand_env, load_mcp_config
from app.llm.runner import run_conversation
from app.llm.tools.registry import ToolRegistry

SERVER_SCRIPT = Path(__file__).parent / "mcp_test_server.py"


@pytest.fixture
def server_cfg() -> MCPServerConfig:
    return MCPServerConfig(name="calc", type="stdio", command=sys.executable, args=[str(SERVER_SCRIPT)])


# ---------- 本地：配置与命名 ----------


def test_tool_name_normalization():
    assert mcp_tool_name("weird name!", "do.thing") == "mcp__weird_name___do_thing"


def test_expand_env(monkeypatch):
    monkeypatch.setenv("MCP_TEST_TOKEN", "abc123")
    assert expand_env("Bearer ${MCP_TEST_TOKEN}") == "Bearer abc123"
    assert expand_env("no placeholder") == "no placeholder"


def test_load_missing_config_returns_empty(tmp_path):
    assert load_mcp_config(str(tmp_path / "nope.json")) == {}


def test_load_config_parses(tmp_path):
    import json

    p = tmp_path / "mcp.json"
    p.write_text(
        json.dumps({"mcpServers": {"calc": {"command": "python", "args": ["s.py"]}}}),
        encoding="utf-8",
    )
    cfgs = load_mcp_config(str(p))
    assert cfgs["calc"].command == "python"
    assert cfgs["calc"].type == "stdio"


# ---------- 真实 stdio server：发现与调用 ----------


@pytest.mark.asyncio
async def test_discover_and_call(server_cfg):
    mgr = MCPManager()
    try:
        defs = await discover_mcp_tools(mgr, {"calc": server_cfg})
        by_name = {d.name: d for d in defs}
        assert set(by_name) == {"mcp__calc__add", "mcp__calc__multiply", "mcp__calc__fail"}
        # inputSchema 透传（FastMCP 生成的 JSON Schema）
        assert by_name["mcp__calc__add"].params_schema["required"] == ["a", "b"]
        # 调用（registry 风格：dict 入参）
        assert await by_name["mcp__calc__add"].handler({"a": 2, "b": 3}) == "5.0"
        assert await by_name["mcp__calc__multiply"].handler({"a": 4, "b": 5}) == "20.0"
        # isError → 错误文本回传（不抛异常）
        err = await by_name["mcp__calc__fail"].handler({"message": "boom"})
        assert "MCP 工具执行错误" in err and "预期失败: boom" in err
    finally:
        await mgr.close_all()


@pytest.mark.asyncio
async def test_session_reuse(server_cfg):
    mgr = MCPManager()
    try:
        s1 = await mgr.get_session(server_cfg)
        s2 = await mgr.get_session(server_cfg)
        assert s1 is s2
    finally:
        await mgr.close_all()


# ---------- 真实 API：模型调用 MCP 工具 ----------


@pytest.mark.ai
@pytest.mark.asyncio
@pytest.mark.skipif(not load_config().api_key, reason="ARK_API_KEY 未配置")
async def test_model_calls_mcp_tool(server_cfg):
    client = create_client("anthropic")
    mgr = MCPManager()
    try:
        defs = await discover_mcp_tools(mgr, {"calc": server_cfg})
        reg = ToolRegistry()
        result = await run_conversation(
            client,
            "请用工具计算 17 乘以 23，直接给出结果。",
            system="你是计算助手，必须调用工具计算。",
            registry=reg,
            tools=defs,
            max_turns=6,
        )
        assert result.tool_calls_executed >= 1
        assert "391" in result.final_text
    finally:
        await mgr.close_all()
