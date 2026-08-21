"""
MCP stdio 服务器运行时检测与依赖安装

- check_stdio_runtime：检测 command 可用性（uvx/npx 回退、安装引导），供添加表单的「检测运行时」
- install_runtime_tool：一键安装缺失的运行时工具（当前支持 uv，走公共 pip 原语）
- install_server_deps：安装服务器配置声明的 deps 到当前容器 Python（与 Skill 机制一致）

安全控制沿用 skill dependency_installer 模式：
- 全局开关 MCP_AUTO_INSTALL_DEPS / 白名单 MCP_ALLOWED_PACKAGES / 超时 MCP_INSTALL_TIMEOUT
- 包声明走公共注入防护校验（app/core/package_install.validate_package_spec）
- 审计写入 skill_install_logs（kind="mcp"）
"""

import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import asyncio
import logging

from app.core.config import settings
from app.core.package_install import build_pip_args, run_install, validate_package_spec
from app.llm.mcp.management.config_store import (
    MCPServerConfig,
    check_command_available,
    clear_command_cache,
)
from app.models.skill import SkillInstallLog
from app.engine.tools.skill.state_store import SkillStateStore

logger = logging.getLogger(__name__)


@dataclass
class RuntimeCheckResult:
    """stdio 服务器运行时检测结果"""

    command_available: bool
    resolved_command: Optional[str] = None
    error: Optional[str] = None            # 含安装引导文案
    install_hint: Optional[str] = None     # "pip install uv" / Node.js 链接
    python_version: Optional[str] = None   # command 为 python* 时附带

    def to_dict(self) -> Dict:
        return {
            "command_available": self.command_available,
            "resolved_command": self.resolved_command,
            "error": self.error,
            "install_hint": self.install_hint,
            "python_version": self.python_version,
        }


def _parse_dep(dep: str) -> str:
    """校验单条依赖声明合法（注入防护），返回原样字符串"""
    package = dep.strip()
    for op in ("==", ">=", "<=", "!=", "~=", ">", "<"):
        if op in package:
            name, _, version = package.partition(op)
            validate_package_spec(name.strip(), version.strip())
            return package
    validate_package_spec(package, "")
    return package


def _allowed_packages() -> set:
    raw = getattr(settings, "MCP_ALLOWED_PACKAGES", "")
    if not raw:
        return set()
    return {p.strip().lower() for p in raw.split(",") if p.strip()}


def _install_timeout() -> int:
    return int(getattr(settings, "MCP_INSTALL_TIMEOUT", 300))


def check_stdio_runtime(cfg: MCPServerConfig) -> RuntimeCheckResult:
    """同步检测 stdio 服务器 command 的可用性（不修改任何状态）"""
    import shutil

    command = (cfg.command or "").strip()
    if not command:
        return RuntimeCheckResult(
            command_available=False,
            error="stdio 服务器缺少 command",
        )

    cmd_name = Path(command).name
    available, _ = check_command_available(command)
    resolved = shutil.which(command) if available else None
    if resolved is None and available:
        # 命中回退命令（如 uvx→uv）时解析回退项
        from app.llm.mcp.management.config_store import resolve_command

        resolved, _err = resolve_command(command)

    result = RuntimeCheckResult(
        command_available=available,
        resolved_command=resolved,
    )

    if not available:
        if cmd_name == "uvx":
            result.error = (
                f"命令 '{command}' 未找到。可一键安装 uv（pip install uv），"
                "或参考 https://docs.astral.sh/uv/getting-started/installation/"
            )
            result.install_hint = "uv"
        elif cmd_name in ("npx", "node", "npm"):
            result.error = f"命令 '{command}' 未找到。请安装 Node.js: https://nodejs.org/"
            result.install_hint = "node"
        else:
            result.error = f"命令 '{command}' 未找到，请确认已安装并添加到 PATH"
    elif cmd_name.startswith("python"):
        result.python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

    return result


async def install_runtime_tool(tool: str, installed_by: str = "system") -> Dict:
    """
    一键安装缺失的运行时工具。当前仅支持 "uv"（pip install uv）；
    node/npx 不自动安装，仅返回引导链接。
    """
    if tool not in ("uv",):
        return {
            "success": False,
            "error": f"不支持自动安装 '{tool}'；Node.js 请手动安装: https://nodejs.org/"
            if tool == "node" else f"不支持自动安装 '{tool}'",
        }

    requirements_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as tmp:
            requirements_path = Path(tmp.name)
        requirements_path.write_text("uv\n", encoding="utf-8")
        args = build_pip_args(sys.executable, requirements_path)
        result = run_install(args, _install_timeout())
    finally:
        if requirements_path is not None:
            try:
                requirements_path.unlink(missing_ok=True)
            except Exception:
                pass

    if result["success"]:
        # 安装成功后清除命令解析缓存，使后续检测/连接立即看到 uv
        clear_command_cache()
        logger.info("[MCP][runtime] uv 安装成功 (%ss)", result["duration_seconds"])
    else:
        logger.warning("[MCP][runtime] uv 安装失败: %s", result["stderr_tail"][-300:])

    return result


async def install_server_deps(
    name: str,
    cfg: MCPServerConfig,
    installed_by: str = "system",
) -> Dict:
    """
    安装 stdio 服务器声明的 deps 到当前容器 Python。

    Returns:
        {installed, satisfied, packages, error, skipped_reason}
    """
    store = SkillStateStore()

    deps: List[str] = list(getattr(cfg, "deps", None) or [])
    if not deps:
        return {"installed": False, "satisfied": True, "packages": [], "error": "", "skipped_reason": "no_deps"}

    if not getattr(settings, "MCP_AUTO_INSTALL_DEPS", True):
        return {"installed": False, "satisfied": False, "packages": [], "error": "", "skipped_reason": "auto_install_disabled"}

    # 白名单
    allowed = _allowed_packages()
    if allowed:
        rejected = [d.split("=")[0].split(">")[0].split("<")[0].strip().lower() for d in deps]
        rejected = [d for d in rejected if d not in allowed]
        if rejected:
            err = f"包被白名单拒绝: {', '.join(rejected)}"
            await store.write_install_log(
                SkillInstallLog(kind="mcp", skill_name=name, packages=[], status="failed", error=err, installed_by=installed_by)
            )
            return {"installed": False, "satisfied": False, "packages": [], "error": err, "skipped_reason": "whitelist_rejected"}

    # 注入防护校验
    validated: List[str] = []
    try:
        validated = [_parse_dep(d) for d in deps]
    except ValueError as exc:
        await store.write_install_log(
            SkillInstallLog(kind="mcp", skill_name=name, packages=[], status="failed", error=str(exc), installed_by=installed_by)
        )
        return {"installed": False, "satisfied": False, "packages": [], "error": str(exc), "skipped_reason": "invalid_spec"}

    logger.info("[MCP][runtime] 开始安装 server '%s' 的依赖: %s", name, validated)

    requirements_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as tmp:
            requirements_path = Path(tmp.name)
        requirements_path.write_text("\n".join(validated) + "\n", encoding="utf-8")
        args = build_pip_args(sys.executable, requirements_path)
        result = run_install(args, _install_timeout())
    finally:
        if requirements_path is not None:
            try:
                requirements_path.unlink(missing_ok=True)
            except Exception:
                pass

    status = "success" if result["success"] else "failed"
    await store.write_install_log(
        SkillInstallLog(
            kind="mcp",
            skill_name=name,
            packages=[{"package": d, "version": "", "hash": ""} for d in validated],
            status=status,
            error=result["stderr_tail"][-500:] if not result["success"] else "",
            duration_seconds=result["duration_seconds"],
            installed_by=installed_by,
        )
    )

    return {
        "installed": True,
        "satisfied": result["success"],
        "packages": validated if result["success"] else [],
        "error": "" if result["success"] else result["stderr_tail"][-500:],
        "skipped_reason": "",
    }


# 同步包装（与 skill install_skill_dependencies_sync 同模式）
def install_server_deps_sync(name: str, cfg: MCPServerConfig, installed_by: str = "system") -> Dict:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        future = asyncio.run_coroutine_threadsafe(install_server_deps(name, cfg, installed_by), loop)
        return future.result(timeout=_install_timeout() + 30)
    return asyncio.run(install_server_deps(name, cfg, installed_by))
