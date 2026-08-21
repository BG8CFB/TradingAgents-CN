"""
本地 skill 安装器

两条入口：
- install_from_zip：上传的 zip 包（远程部署主路径）
- install_from_local_path：服务器上已存在的目录（本机/内网场景）

安全控制：
- zip slip：逐条目 resolve 后必须在解压目标内；拒绝绝对路径 / `..` / 盘符
- 拒绝符号链接条目；解压后清除可执行位（Linux）
- 大小双限制：解压前按 ZipInfo.file_size 预检，解压后实测复核
- 顶层（或唯一子目录）必须含 SKILL.md，多包 zip 拒绝
"""

import logging
import shutil
import stat
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

from app.core.config import settings
from app.engine.tools.skill.git_installer import _move_to_user_dir
from app.engine.tools.skill.loader import get_cache_skills_dir
from app.engine.tools.skill.package_validator import validate_skill_package

logger = logging.getLogger(__name__)

# 单文件上限（与 ClawHub raw 文件限制对齐）
_MAX_SINGLE_FILE_BYTES = 10 * 1024 * 1024


def mark_skill_source(
    skill_dir: Path,
    source_type: str,
    url: str = "",
    version: str = "",
    installed_by: str = "",
) -> None:
    """
    在 skill 目录写入/更新 manifest.yaml 的 source 信息（幂等）。

    registry 判定来源时会优先读 manifest.source.type 细化 local 分类，
    市场/zip/路径安装分别写 registry / local / local。
    """
    manifest_path = Path(skill_dir) / "manifest.yaml"
    data: dict = {}
    if manifest_path.exists():
        try:
            data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}

    source = data.get("source") or {}
    if not isinstance(source, dict):
        source = {}
    source.update(
        {
            "type": source_type,
            "url": url or source.get("url", ""),
            "commit": source.get("commit", ""),
            "installed_at": (source.get("installed_at") or datetime.now(timezone.utc).isoformat()),
            "installed_by": installed_by or source.get("installed_by", ""),
        }
    )
    if version:
        source["version"] = version
    data["source"] = source
    if not data.get("skill_name"):
        data["skill_name"] = Path(skill_dir).name

    manifest_path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def _reload_registry() -> None:
    from app.engine.tools.skill.registry import SkillRegistry

    try:
        SkillRegistry.get_instance().reload()
    except Exception as e:
        logger.warning(f"[LocalInstaller] reload registry 失败: {e}")


def _max_upload_bytes() -> int:
    return int(getattr(settings, "SKILL_UPLOAD_MAX_SIZE_MB", 20)) * 1024 * 1024


def _safe_extract_zip(zip_path: Path, dest: Path) -> None:
    """
    安全解压：zip slip / 符号链接 / 大小 / 单文件限制。

    Raises:
        RuntimeError: 任一安全校验失败（调用方负责清理 dest）
    """
    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)

    total_declared = 0
    with zipfile.ZipFile(zip_path) as zf:
        infos = zf.infolist()
        for info in infos:
            # 符号链接条目（外部属性高 16 位为 POSIX mode，S_ISLNK 判断）
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise RuntimeError(f"zip 内含符号链接条目，拒绝解压: {info.filename}")
            total_declared += info.file_size
            if info.file_size > _MAX_SINGLE_FILE_BYTES:
                raise RuntimeError(f"zip 内单文件超过 10MB 上限: {info.filename}")

        if total_declared > _max_upload_bytes():
            raise RuntimeError(
                f"zip 解压总大小超过上限（{getattr(settings, 'SKILL_UPLOAD_MAX_SIZE_MB', 20)}MB）"
            )

        for info in infos:
            target = (dest / info.filename).resolve()
            # 防 zip slip：解压目标必须仍在 dest 内
            if target != dest and not target.is_relative_to(dest):
                raise RuntimeError(f"zip 条目路径可疑（zip slip），拒绝: {info.filename}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            # 清除可执行位（Linux；Windows 无此语义，忽略异常）
            try:
                target.chmod(target.stat().st_mode & 0o644)
            except OSError:
                pass

    # 解压后实测复核（防声明大小造假）
    actual_total = sum(p.stat().st_size for p in dest.rglob("*") if p.is_file())
    if actual_total > _max_upload_bytes():
        raise RuntimeError("zip 解压后实际大小超过上限")


def _locate_skill_root(extracted: Path) -> Path:
    """定位 SKILL.md 所在目录：顶层优先，否则唯一子目录；多包/未找到则报错"""
    if (extracted / "SKILL.md").exists():
        return extracted

    subdirs = [d for d in extracted.iterdir() if d.is_dir() and not d.name.startswith(".")]
    if len(subdirs) == 1 and (subdirs[0] / "SKILL.md").exists():
        return subdirs[0]

    raise RuntimeError("zip 内未找到合法的 skill 包（顶层或唯一子目录需含 SKILL.md）")


def _finalize_install(
    skill_root: Path,
    source_type: str,
    url: str = "",
    version: str = "",
    installed_by: str = "",
) -> dict:
    """公共收尾：校验 → 重命名 → 落位 → 标记来源 → reload"""
    skill_name, err = validate_skill_package(skill_root)
    if err:
        return {"success": False, "skill_name": skill_name or "", "installed_path": "", "error": err}

    # 目录名与 skill_name 一致（Agent Skills 规范）
    if skill_root.name != skill_name:
        new_root = skill_root.parent / skill_name
        if new_root.exists():
            shutil.rmtree(new_root, ignore_errors=True)
        skill_root = skill_root.rename(new_root)

    try:
        final_path = _move_to_user_dir(skill_root, skill_name)
    except Exception as e:
        shutil.rmtree(skill_root, ignore_errors=True)
        return {
            "success": False,
            "skill_name": skill_name,
            "installed_path": "",
            "error": f"移动到用户目录失败: {e}",
        }

    try:
        mark_skill_source(
            final_path, source_type, url=url, version=version, installed_by=installed_by
        )
    except Exception as e:
        logger.warning(f"[LocalInstaller] 写入 source 标记失败: {e}")

    _reload_registry()
    logger.info(f"[LocalInstaller] 已安装 skill: {skill_name} (source={source_type})")
    return {"success": True, "skill_name": skill_name, "installed_path": str(final_path), "error": ""}


def install_from_zip(zip_path, installed_by: str = "user") -> dict:
    """
    从 zip 包安装 skill。

    Args:
        zip_path: zip 文件路径（str/Path）
    Returns:
        {success, skill_name, installed_path, error}
    """
    zip_path = Path(zip_path)
    if not zip_path.exists():
        return {"success": False, "skill_name": "", "installed_path": "", "error": f"zip 文件不存在: {zip_path}"}
    if not zipfile.is_zipfile(zip_path):
        return {"success": False, "skill_name": "", "installed_path": "", "error": "不是合法的 zip 文件"}

    pending = Path(get_cache_skills_dir()) / "_pending_zip"
    shutil.rmtree(pending, ignore_errors=True)
    try:
        _safe_extract_zip(zip_path, pending)
        skill_root = _locate_skill_root(pending)
    except RuntimeError as e:
        shutil.rmtree(pending, ignore_errors=True)
        return {"success": False, "skill_name": "", "installed_path": "", "error": str(e)}
    except zipfile.BadZipFile as e:
        shutil.rmtree(pending, ignore_errors=True)
        return {"success": False, "skill_name": "", "installed_path": "", "error": f"zip 文件损坏: {e}"}

    return _finalize_install(skill_root, "local", url=str(zip_path), installed_by=installed_by)


def install_from_local_path(src_dir: str, installed_by: str = "user") -> dict:
    """
    从服务器本地目录导入 skill（复制，不动源目录）。

    Args:
        src_dir: 服务器上的 skill 目录绝对路径（须含 SKILL.md）
    """
    src = Path(src_dir).expanduser().resolve()
    if not src.is_dir():
        return {"success": False, "skill_name": "", "installed_path": "", "error": f"目录不存在: {src}"}
    if not (src / "SKILL.md").exists():
        return {"success": False, "skill_name": "", "installed_path": "", "error": f"目录缺少 SKILL.md: {src}"}

    pending = Path(get_cache_skills_dir()) / "_pending_local"
    shutil.rmtree(pending, ignore_errors=True)
    try:
        shutil.copytree(src, pending)
    except Exception as e:
        shutil.rmtree(pending, ignore_errors=True)
        return {"success": False, "skill_name": "", "installed_path": "", "error": f"复制目录失败: {e}"}

    return _finalize_install(pending, "local", url=str(src), installed_by=installed_by)
