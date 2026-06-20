"""
Skill 依赖自动安装器

首次加载 skill 时检查依赖，未满足时自动 pip install 到当前容器环境。

安全控制（缓解供应链风险）：
- 强制走默认 PyPI index，禁 --index-url / --extra-index-url
- manifest 的 hash 字段若存在则传 --require-hashes
- 全局开关 SKILL_AUTO_INSTALL（默认 true，可关）
- 可选白名单 SKILL_ALLOWED_PACKAGES（逗号分隔，空则不限制）
- --no-input 防止 pip 交互卡死
- 安装记录写入 MongoDB skill_install_logs 审计
- 全部在 Docker 容器内执行，不污染宿主机

注意：安装过程是同步阻塞的（pip install 本身是同步的），但本模块的入口
ensure_skill_dependencies 是 async——因为 SkillStateStore 的写入是 async。
"""
import asyncio
import logging
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List

from app.core.config import settings
from app.engine.tools.skill.availability import check_skill_dependencies_raw
from app.engine.tools.skill.registry import SkillRegistry
from app.engine.tools.skill.state_store import SkillStateStore
from app.models.skill import SkillInstallLog, SkillManifest, SkillPythonDependency

logger = logging.getLogger(__name__)


def _is_auto_install_enabled() -> bool:
    """读取全局自动安装开关"""
    return getattr(settings, "SKILL_AUTO_INSTALL", True)


def _get_allowed_packages() -> set:
    """读取包名白名单（逗号分隔），空集合表示不限制"""
    raw = getattr(settings, "SKILL_ALLOWED_PACKAGES", "")
    if not raw:
        return set()
    return {p.strip().lower() for p in raw.split(",") if p.strip()}


def _get_install_timeout() -> int:
    """读取单次 pip install 超时（秒）"""
    return int(getattr(settings, "SKILL_INSTALL_TIMEOUT", 300))


def _validate_against_whitelist(manifest: SkillManifest) -> List[str]:
    """
    校验 manifest 声明的包是否都在白名单内。

    Returns:
        被白名单拒绝的包名列表（空列表表示全部通过）
    """
    allowed = _get_allowed_packages()
    if not allowed:
        return []
    rejected = []
    for dep in manifest.python_dependencies:
        if dep.package.lower() not in allowed:
            rejected.append(dep.package)
    return rejected


def _build_pip_args(
    deps: List[SkillPythonDependency],
    requirements_file: Path,
) -> List[str]:
    """
    构造 pip install 命令参数。

    安全约束：
    - 不传 --index-url / --extra-index-url（强制走默认 PyPI）
    - 若任一依赖声明了 hash，则全部走 --require-hashes
    - --no-input 防交互
    --disable-pip-version-check 减少输出噪音
    """
    args = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "-r",
        str(requirements_file),
        "--no-input",
        "--disable-pip-version-check",
        "--no-warn-script-location",
    ]

    has_hash = any(dep.hash for dep in deps)
    if has_hash:
        args.append("--require-hashes")

    return args


def _write_requirements(
    deps: List[SkillPythonDependency],
    requirements_file: Path,
) -> None:
    """
    写临时 requirements.txt。

    格式：
        mplfinance>=0.12.10b0
        ta-lib==0.4.28 --hash=sha256:abc...
    """
    lines = []
    for dep in deps:
        if dep.hash:
            lines.append(f"{dep.package}{dep.version} --hash={dep.hash}")
        else:
            lines.append(f"{dep.package}{dep.version}")
    requirements_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_pip_install(args: List[str], timeout: int) -> Dict:
    """
    执行 pip install 子进程。

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
            "stderr_tail": f"pip install 超时（{timeout}秒）",
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


async def install_skill_dependencies(
    name: str,
    installed_by: str = "system",
) -> Dict:
    """
    安装指定 skill 的全部 Python 依赖。

    流程：
    1. 检查全局开关；关闭则直接返回
    2. 读取 manifest；无 manifest 视为无需安装
    3. 白名单校验；拒绝则记录审计日志
    4. check_dependencies；若已满足则跳过
    5. 写临时 requirements.txt + 调用 pip install
    6. 安装后 re-check；写审计日志；更新 skill_state

    Returns:
        {
            "installed": bool,            # 是否触发了安装
            "satisfied": bool,            # 最终是否满足
            "packages_installed": List[str],
            "error": str,
            "skipped_reason": str,        # 若未触发安装的原因
        }
    """
    registry = SkillRegistry.get_instance()
    store = SkillStateStore()

    # 1. 全局开关
    if not _is_auto_install_enabled():
        logger.info(f"[SkillInstaller] 自动安装已关闭，跳过 {name}")
        return {
            "installed": False,
            "satisfied": False,
            "packages_installed": [],
            "error": "",
            "skipped_reason": "auto_install_disabled",
        }

    # 2. 读取 manifest
    manifest = registry.get_manifest(name)
    if manifest is None:
        return {
            "installed": False,
            "satisfied": True,
            "packages_installed": [],
            "error": "",
            "skipped_reason": "no_manifest",
        }

    if not manifest.python_dependencies:
        # 无 Python 依赖，直接标记为已满足
        await store.record_installed_dependencies(name, [])
        return {
            "installed": False,
            "satisfied": True,
            "packages_installed": [],
            "error": "",
            "skipped_reason": "no_python_dependencies",
        }

    # 3. 白名单校验
    rejected = _validate_against_whitelist(manifest)
    if rejected:
        err = f"包被白名单拒绝: {', '.join(rejected)}"
        logger.warning(f"[SkillInstaller] {name} {err}")
        await store.write_install_log(
            SkillInstallLog(
                skill_name=name,
                source_url=manifest.source.url,
                source_commit=manifest.source.commit,
                packages=[],
                status="failed",
                error=err,
                installed_by=installed_by,
            )
        )
        return {
            "installed": False,
            "satisfied": False,
            "packages_installed": [],
            "error": err,
            "skipped_reason": "whitelist_rejected",
        }

    # 4. 预检查——若已满足则跳过
    pre_check = check_skill_dependencies_raw(name)
    if pre_check["satisfied"]:
        await store.record_installed_dependencies(
            name,
            [d.package for d in manifest.python_dependencies],
        )
        return {
            "installed": False,
            "satisfied": True,
            "packages_installed": [],
            "error": "",
            "skipped_reason": "already_satisfied",
        }

    # 5. 执行安装
    deps_to_install = manifest.python_dependencies
    logger.info(
        f"[SkillInstaller] 开始安装 {name} 的依赖: "
        f"{[d.package for d in deps_to_install]}"
    )

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as tmp:
        requirements_path = Path(tmp.name)
    _write_requirements(deps_to_install, requirements_path)

    try:
        pip_args = _build_pip_args(deps_to_install, requirements_path)
        timeout = _get_install_timeout()
        result = _run_pip_install(pip_args, timeout)
    finally:
        try:
            requirements_path.unlink(missing_ok=True)
        except Exception:
            pass

    # 6. 后置检查与审计
    post_check = check_skill_dependencies_raw(name)
    availability_dict = post_check.get("availability") or {}
    deps_list = availability_dict.get("dependencies", []) if isinstance(
        availability_dict, dict
    ) else []
    satisfied_packages = [
        d["package"] for d in deps_list if isinstance(d, dict) and d.get("satisfied")
    ]

    status = "success" if result["success"] and post_check["satisfied"] else "failed"
    if result["success"] and not post_check["satisfied"]:
        status = "partial"

    await store.write_install_log(
        SkillInstallLog(
            skill_name=name,
            source_url=manifest.source.url,
            source_commit=manifest.source.commit,
            packages=[
                {"package": d.package, "version": d.version, "hash": d.hash}
                for d in deps_to_install
            ],
            status=status,
            error=result["stderr_tail"][-500:] if not result["success"] else "",
            duration_seconds=result["duration_seconds"],
            installed_by=installed_by,
        )
    )

    if post_check["satisfied"]:
        await store.record_installed_dependencies(name, satisfied_packages)
        logger.info(
            f"[SkillInstaller] {name} 安装成功: {satisfied_packages}"
            f" ({result['duration_seconds']}s)"
        )
    else:
        logger.warning(
            f"[SkillInstaller] {name} 安装未完全成功: status={status}, "
            f"stderr_tail={result['stderr_tail'][-200:]}"
        )

    return {
        "installed": True,
        "satisfied": post_check["satisfied"],
        "packages_installed": satisfied_packages,
        "error": "" if result["success"] else result["stderr_tail"][-500:],
        "skipped_reason": "",
    }


def install_skill_dependencies_sync(
    name: str,
    installed_by: str = "system",
) -> Dict:
    """install_skill_dependencies 的同步包装（供 SkillRegistry 同步回调使用）"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 已在事件循环中（如 FastAPI 请求处理），创建 task 并等待
            future = asyncio.run_coroutine_threadsafe(
                install_skill_dependencies(name, installed_by), loop
            )
            return future.result(timeout=_get_install_timeout() + 30)
    except RuntimeError:
        pass
    # 无事件循环，直接运行
    return asyncio.run(install_skill_dependencies(name, installed_by))


async def ensure_all_skills_dependencies() -> Dict:
    """
    启动时调用：为所有已发现的 skill 确保依赖就绪。

    用于容器重启后从 skill_state 重装已记录的依赖（幂等）。

    Returns:
        {
            "total": int,
            "installed": int,
            "failed": int,
            "skipped": int,
            "details": {skill_name: result_dict},
        }
    """
    registry = SkillRegistry.get_instance()
    all_skills = registry.list_all_skills()

    total = len(all_skills)
    installed_count = 0
    failed_count = 0
    skipped_count = 0
    details: Dict[str, Dict] = {}

    for skill in all_skills:
        name = skill["name"]
        if not skill.get("has_manifest"):
            skipped_count += 1
            details[name] = {"skipped_reason": "no_manifest"}
            continue

        try:
            result = await install_skill_dependencies(name, "system:startup")
            details[name] = result
            if result["installed"]:
                if result["satisfied"]:
                    installed_count += 1
                else:
                    failed_count += 1
            else:
                skipped_count += 1
        except Exception as e:
            logger.error(f"[SkillInstaller] 启动时安装 {name} 异常: {e}")
            failed_count += 1
            details[name] = {"installed": False, "satisfied": False, "error": str(e)}

    logger.info(
        f"[SkillInstaller] 启动依赖安装完成: "
        f"total={total}, installed={installed_count}, "
        f"failed={failed_count}, skipped={skipped_count}"
    )
    return {
        "total": total,
        "installed": installed_count,
        "failed": failed_count,
        "skipped": skipped_count,
        "details": details,
    }
