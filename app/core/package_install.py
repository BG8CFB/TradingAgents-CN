"""
通用 pip 包安装原语（从 app/engine/tools/skill/dependency_installer.py 抽出）

供 Skill 依赖安装与 MCP 服务器依赖安装（app/llm/mcp/management/runtime.py）共用。

安全控制：
- 强制走默认 PyPI index，禁 --index-url / --extra-index-url
- 包名/版本做严格字符校验（R13-ET-03：防 requirements 注入切换安装源）
- --no-input 防交互；子进程带超时
"""

import re
import subprocess
import time
from pathlib import Path
from typing import Dict, List

import logging

logger = logging.getLogger(__name__)

# package: 只允许字母、数字、下划线、连字符、点（PEP 508 名称规范）
PACKAGE_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9._-]*[a-zA-Z0-9])?$")
# version: PEP 440 版本约束字符，禁止换行、空格、-- 选项
VERSION_RE = re.compile(r"^[a-zA-Z0-9_.<>=!~;,+^*-]*$")


def validate_package_spec(package: str, version: str = "") -> None:
    """
    校验包名与版本约束字符，非法即抛 ValueError（防 requirements 注入）。
    """
    if not PACKAGE_RE.match(package):
        logger.error(f"[PackageInstall] 包名含非法字符，拒绝安装: {package!r}")
        raise ValueError(f"包名含非法字符（仅允许字母、数字、下划线、连字符、点）: {package}")

    if version and not VERSION_RE.match(version):
        logger.error(f"[PackageInstall] 版本约束含非法字符，拒绝安装: {package}{version!r}")
        raise ValueError(f"版本约束含非法字符（禁止换行、空格、-- 选项）: {package}{version}")


def write_requirements(lines: List[str], requirements_file: Path) -> None:
    """写入 requirements 行（每行已经过 validate 检查的 'pkg==1.0 [--hash=...]'）"""
    requirements_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_pip_args(
    python_exec: str,
    requirements_file: Path,
    require_hashes: bool = False,
) -> List[str]:
    """
    构造 pip install 命令参数。

    安全约束：
    - 不传 --index-url / --extra-index-url（强制走默认 PyPI）
    - require_hashes=True 时走 --require-hashes
    - --no-input 防交互
    """
    args = [
        python_exec,
        "-m",
        "pip",
        "install",
        "-r",
        str(requirements_file),
        "--no-input",
        "--disable-pip-version-check",
        "--no-warn-script-location",
    ]
    if require_hashes:
        args.append("--require-hashes")
    return args


def run_install(args: List[str], timeout: int) -> Dict:
    """
    执行安装子进程（pip install / 其他安装器均可）。

    Returns:
        {
            "success": bool,
            "returncode": int,
            "stdout_tail": str,   # stdout 最后 2000 字符（用于错误诊断）
            "stderr_tail": str,
            "duration_seconds": float,
        }
    """
    start = time.time()
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        duration = time.time() - start
        return {
            "success": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout_tail": proc.stdout[-2000:] if proc.stdout else "",
            "stderr_tail": proc.stderr[-2000:] if proc.stderr else "",
            "duration_seconds": round(duration, 2),
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "returncode": -1,
            "stdout_tail": "",
            "stderr_tail": f"安装子进程超时（{timeout}秒）",
            "duration_seconds": float(timeout),
        }
    except Exception as e:
        return {
            "success": False,
            "returncode": -2,
            "stdout_tail": "",
            "stderr_tail": f"子进程执行失败: {e}",
            "duration_seconds": round(time.time() - start, 2),
        }
