"""
Skill Git URL 安装器

从 Git URL 拉取 skill 到本地缓存目录，校验 manifest 后移动到用户目录。

安全控制：
- 强制校验 host 在 SKILL_GIT_TRUSTED_HOSTS 白名单内
- 使用 --depth 1 浅克隆，避免拉取完整历史（含可能的恶意 commit）
- 克隆后立即删除 .git 目录（防止 git hook 执行）
- 不自动执行 skill 内的任何脚本（只做文件拉取与 manifest 校验）
"""
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from app.core.config import settings
from app.engine.tools.skill.loader import get_cache_skills_dir, get_default_user_skills_dir
from app.engine.tools.skill.manifest import load_manifest

logger = logging.getLogger(__name__)


def _extract_host(url: str) -> str:
    """从 URL 提取主机名"""
    try:
        parsed = urlparse(url)
        return parsed.hostname or ""
    except Exception:
        return ""


def _get_trusted_hosts() -> set:
    """读取可信主机白名单"""
    raw = getattr(settings, "SKILL_GIT_TRUSTED_HOSTS", "")
    if not raw:
        return set()
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def _validate_git_url(url: str, trusted_hosts: Optional[set] = None) -> Optional[str]:
    """
    校验 Git URL 是否可信。

    Args:
        url: 待校验的 Git URL
        trusted_hosts: 显式传入的可信主机集合；None 时从全局 settings 读取

    Returns:
        错误信息；None 表示通过
    """
    if not url:
        return "URL 为空"

    if not (url.startswith("https://") or url.startswith("git@") or url.startswith("ssh://")):
        return "仅允许 https/ssh 协议的 Git URL"

    host = _extract_host(url)
    if not host:
        return f"无法解析 URL 主机: {url}"

    if trusted_hosts is None:
        trusted_hosts = _get_trusted_hosts()
    if trusted_hosts and host.lower() not in trusted_hosts:
        return f"主机 {host} 不在可信白名单内（SKILL_GIT_TRUSTED_HOSTS={trusted_hosts}）"

    return None


def _clone_to_cache(url: str, skill_name: str) -> Path:
    """
    克隆到缓存目录。

    使用 --depth 1 浅克隆；克隆后删除 .git 目录防止 git hook 执行。
    """
    cache_root = Path(get_cache_skills_dir())
    cache_root.mkdir(parents=True, exist_ok=True)

    target = cache_root / skill_name
    if target.exists():
        # 已存在同名缓存，先清空再克隆
        shutil.rmtree(target, ignore_errors=True)

    args = [
        "git",
        "clone",
        "--depth",
        "1",
        url,
        str(target),
    ]

    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"git clone 失败: {proc.stderr[-500:]}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("git clone 超时（120秒）")
    except FileNotFoundError:
        raise RuntimeError("git 命令未找到，请安装 git")

    # 删除 .git 目录（防止 git hook 被触发）
    git_dir = target / ".git"
    if git_dir.exists():
        shutil.rmtree(git_dir, ignore_errors=True)

    return target


def _move_to_user_dir(cache_path: Path, skill_name: str) -> Path:
    """
    把校验通过的 skill 从缓存移动到用户目录。

    若用户目录已存在同名 skill，先备份再覆盖（不直接删除用户文件）。
    """
    user_dir = Path(get_default_user_skills_dir())
    user_dir.mkdir(parents=True, exist_ok=True)

    target = user_dir / skill_name
    if target.exists():
        backup = target.with_name(f"{skill_name}.bak")
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        target.rename(backup)
        logger.info(f"[SkillGitInstaller] 已备份原有 skill 到 {backup.name}")

    shutil.move(str(cache_path), str(target))
    return target


def install_from_git(url: str, trusted_hosts_override: Optional[list] = None) -> dict:
    """
    从 Git URL 安装 skill。

    流程：
    1. 校验 URL 与主机白名单（含临时 trusted_hosts_override）
    2. git clone 到缓存目录（--depth 1）
    3. 删除 .git 目录
    4. 校验 SKILL.md 与 manifest 存在
    5. 从 SKILL.md 或目录推断 skill_name
    6. 移动到用户目录
    7. 重新发现并注册

    Args:
        url: Git URL
        trusted_hosts_override: 临时可信主机覆盖（API 调用方传入，与全局配置合并）

    Returns:
        {
            "success": bool,
            "skill_name": str,
            "installed_path": str,
            "error": str,
        }
    """
    # 合并 trusted_hosts（仅用于本次校验，不修改全局配置）
    merged_hosts = _get_trusted_hosts()
    if trusted_hosts_override:
        merged_hosts = merged_hosts.union(
            {h.strip().lower() for h in trusted_hosts_override if h}
        )

    return _do_install(url, merged_hosts)


def _do_install(url: str, trusted_hosts: Optional[set] = None) -> dict:
    """实际安装逻辑（已校验 URL）"""
    err = _validate_git_url(url, trusted_hosts)
    if err:
        return {
            "success": False,
            "skill_name": "",
            "installed_path": "",
            "error": err,
        }

    try:
        # 先克隆到一个临时名称，待读取 SKILL.md 后再确定真实名称
        temp_name = "_pending_install"
        cache_path = _clone_to_cache(url, temp_name)
    except Exception as e:
        return {
            "success": False,
            "skill_name": "",
            "installed_path": "",
            "error": str(e),
        }

    # 校验 SKILL.md 存在
    skill_md = cache_path / "SKILL.md"
    if not skill_md.exists():
        shutil.rmtree(cache_path, ignore_errors=True)
        return {
            "success": False,
            "skill_name": "",
            "installed_path": "",
            "error": "Git 仓库根目录缺少 SKILL.md，不是合法的 skill 包",
        }

    # 解析 skill_name
    from app.engine.tools.skill.loader import parse_skill_metadata
    meta = parse_skill_metadata(str(skill_md))
    skill_name = meta.get("name") or cache_path.name

    # 验证目录名与 skill_name 一致（Agent Skills 规范要求）
    # 重命名缓存目录
    if cache_path.name != skill_name:
        new_cache = cache_path.parent / skill_name
        if new_cache.exists():
            shutil.rmtree(new_cache, ignore_errors=True)
        cache_path = cache_path.rename(new_cache)

    # 校验 manifest（若存在）
    manifest = load_manifest(str(cache_path))
    if manifest is not None and manifest.skill_name != skill_name:
        shutil.rmtree(cache_path, ignore_errors=True)
        return {
            "success": False,
            "skill_name": skill_name,
            "installed_path": "",
            "error": f"manifest.skill_name ({manifest.skill_name}) 与目录名 ({skill_name}) 不一致",
        }

    try:
        final_path = _move_to_user_dir(cache_path, skill_name)
    except Exception as e:
        shutil.rmtree(cache_path, ignore_errors=True)
        return {
            "success": False,
            "skill_name": skill_name,
            "installed_path": "",
            "error": f"移动到用户目录失败: {e}",
        }

    logger.info(f"[SkillGitInstaller] 已从 Git 安装 skill: {skill_name} <- {url}")

    # 触发重新发现
    try:
        from app.engine.tools.skill.registry import SkillRegistry
        registry = SkillRegistry.get_instance()
        registry.reload()
    except Exception as e:
        logger.warning(f"[SkillGitInstaller] reload registry 失败: {e}")

    return {
        "success": True,
        "skill_name": skill_name,
        "installed_path": str(final_path),
        "error": "",
    }


def uninstall_skill(skill_name: str, force: bool = False) -> dict:
    """
    卸载 skill。

    安全约束：
    - 默认只允许卸载 Git/registry 来源的 skill（在 .cache 或标记为 git/registry）
    - 本地用户 skill 必须显式 force=True 才卸载（防止误删用户手写文件）
    - builtin skill 不允许卸载（只读）

    Args:
        skill_name: skill 名
        force: 是否强制卸载本地用户 skill

    Returns:
        {"success": bool, "removed_path": str, "error": str}
    """
    from app.engine.tools.skill.registry import SkillRegistry
    from app.engine.tools.skill.loader import get_builtin_skills_dir

    registry = SkillRegistry.get_instance()
    all_skills = {s["name"]: s for s in registry.list_all_skills()}

    if skill_name not in all_skills:
        return {"success": False, "removed_path": "", "error": f"skill 不存在: {skill_name}"}

    skill_meta = all_skills[skill_name]
    source_type = skill_meta.get("source_type", "local")
    skill_dir = skill_meta.get("skill_dir", "")

    # builtin 禁止卸载
    if source_type == "builtin" or skill_dir.startswith(get_builtin_skills_dir()):
        return {"success": False, "removed_path": "", "error": "内置 skill 不允许卸载"}

    # 本地用户 skill 需 force
    if source_type == "local" and not force:
        return {
            "success": False,
            "removed_path": "",
            "error": "本地 skill 需 force=true 才允许卸载（防止误删用户文件）",
        }

    if not skill_dir or not Path(skill_dir).exists():
        return {"success": False, "removed_path": "", "error": f"skill 目录不存在: {skill_dir}"}

    # 卸载 builtin 工具入口
    try:
        from app.engine.tools.skill.entrypoint_loader import unload_skill_entrypoints
        unload_skill_entrypoints(skill_name)
    except Exception as e:
        logger.warning(f"卸载 skill 入口失败 {skill_name}: {e}")

    # 删除目录
    try:
        shutil.rmtree(skill_dir)
    except Exception as e:
        return {"success": False, "removed_path": "", "error": f"删除目录失败: {e}"}

    # 从 registry 移除
    try:
        registry.reload()
    except Exception as e:
        logger.warning(f"reload registry 失败: {e}")

    # 删除持久化状态
    try:
        from app.engine.tools.skill.state_store import SkillStateStore
        store = SkillStateStore()
        # 异步删除，fire-and-forget
        import asyncio
        try:
            asyncio.get_event_loop().create_task(store.delete_state(skill_name))
        except Exception:
            pass
    except Exception as e:
        logger.warning(f"删除 skill_state 失败: {e}")

    logger.info(f"[SkillGitInstaller] 已卸载 skill: {skill_name} (source={source_type})")
    return {"success": True, "removed_path": skill_dir, "error": ""}
