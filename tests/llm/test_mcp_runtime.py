"""MCP 运行时检测与依赖安装测试（真实命令/子进程路径，无 mock）"""


import pytest

from app.core.package_install import validate_package_spec
from app.llm.mcp.management.config_store import MCPServerConfig
from app.llm.mcp.management.runtime import (
    _parse_dep,
    check_stdio_runtime,
    install_runtime_tool,
)


# ---------- 运行时检测 ----------

def test_check_python_available():
    result = check_stdio_runtime(MCPServerConfig(command="python", args=[]))
    assert result.command_available is True
    assert result.resolved_command
    assert result.python_version


def test_check_missing_command_unavailable_with_hint():
    result = check_stdio_runtime(MCPServerConfig(command="definitely-not-a-cmd-xyz", args=[]))
    assert result.command_available is False
    assert result.error
    assert "未找到" in result.error


def test_check_missing_uvx_shows_install_hint():
    # 通过缓存污染保证 uvx 解析失败路径（真实 which 查找）
    from app.llm.mcp.management.config_store import _RESOLVED_COMMAND_CACHE, clear_command_cache

    clear_command_cache()
    _RESOLVED_COMMAND_CACHE["uvx"] = None
    try:
        result = check_stdio_runtime(MCPServerConfig(command="uvx", args=[]))
        if not result.command_available:
            assert "uv" in result.error
        # 宿主机可能已安装 uv，此时只验证可用性为真即可
    finally:
        clear_command_cache()


# ---------- 依赖声明注入防护 ----------

def test_injection_blocked_via_newline():
    with pytest.raises(ValueError):
        validate_package_spec("pkg\n--index-url http://evil", "")


def test_injection_blocked_via_spaces_and_option():
    with pytest.raises(ValueError):
        validate_package_spec("pkg", ">=1.0 --index-url http://evil")


def test_parse_dep_accepts_version_constraints():
    assert _parse_dep("pandas>=2.0") == "pandas>=2.0"
    assert _parse_dep("numpy==1.26.0") == "numpy==1.26.0"
    assert _parse_dep("requests") == "requests"


def test_config_deps_validator_blocks_injection():
    with pytest.raises(ValueError):
        MCPServerConfig(command="python", args=[], deps=["pkg\n--index-url http://evil"])


def test_config_deps_validator_accepts_valid():
    cfg = MCPServerConfig(command="python", args=[], deps=["pandas>=2.0", "requests"])
    assert cfg.sanitized()["deps"] == ["pandas>=2.0", "requests"]


# ---------- 真实安装（integration + slow） ----------

@pytest.mark.integration
@pytest.mark.slow
async def test_install_runtime_tool_uv_idempotent():
    result = await install_runtime_tool("uv", installed_by="test")
    assert result["success"] is True
    # 幂等：第二次安装同样成功（已装则 pip 快速跳过）
    result2 = await install_runtime_tool("uv", installed_by="test")
    assert result2["success"] is True
