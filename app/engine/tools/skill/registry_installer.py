"""
ClawHub 市场 skill 安装编排

流程：
1. 市场详情读 skill 名与 canonical_url（reference 支持 "owner/slug" 消歧）
2. 版本缺省取 latest；拉该版本文件清单
3. 逐文件下载到 .cache/_pending_registry/{name}/（文件数与总量上限防拉爆），
   清单带 sha256 时逐文件校验
4. 复用公共校验（package_validator）→ 落位 → 写 manifest source.type="registry" → reload

任一步失败清理 pending 目录。
"""

import asyncio
import hashlib
import logging
import shutil
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.engine.tools.skill.loader import get_cache_skills_dir
from app.engine.tools.skill.local_installer import _finalize_install
from app.engine.tools.skill.marketplace import get_marketplace_client

logger = logging.getLogger(__name__)

# 文件数上限（防清单异常导致拉爆）
_MAX_FILE_COUNT = 200


def _max_total_bytes() -> int:
    return int(getattr(settings, "SKILL_UPLOAD_MAX_SIZE_MB", 20)) * 1024 * 1024 * 2


async def install_from_marketplace(reference: str, version: Optional[str] = None) -> dict:
    """
    从 ClawHub 市场安装 skill。

    Args:
        reference: 市场引用，"owner/slug"（推荐，消歧）或裸 "slug"
        version: 指定版本；空取 latest

    Returns:
        {success, skill_name, installed_path, version, error}
    """
    if not reference or not reference.strip():
        return {"success": False, "skill_name": "", "installed_path": "", "version": "", "error": "引用为空"}

    reference = reference.strip().lstrip("@")
    client = get_marketplace_client()
    try:
        detail = await client.get_skill(reference)
    except Exception as e:
        return {"success": False, "skill_name": "", "installed_path": "", "version": "", "error": str(e)}

    canonical_ref = detail.get("reference") or reference
    if not version:
        version = detail.get("latest_version") or ""

    try:
        if version:
            files = await client.get_version_files(canonical_ref, version)
        else:
            files = []
        if not files:
            # 无版本信息/空清单时至少拉 SKILL.md（tag=latest）
            files = [{"path": "SKILL.md", "size": 0, "sha256": ""}]
    except Exception as e:
        return {"success": False, "skill_name": "", "installed_path": "", "version": version, "error": str(e)}

    if len(files) > _MAX_FILE_COUNT:
        return {
            "success": False,
            "skill_name": "",
            "installed_path": "",
            "version": version,
            "error": f"市场文件数超过上限（{_MAX_FILE_COUNT}）",
        }

    # SKILL.md 必须在清单内
    paths = [f["path"].lstrip("/") for f in files]
    if "SKILL.md" not in paths:
        return {
            "success": False,
            "skill_name": "",
            "installed_path": "",
            "version": version,
            "error": "市场版本文件清单缺少 SKILL.md，不是合法的 skill 包",
        }

    pending = Path(get_cache_skills_dir()) / "_pending_registry"
    shutil.rmtree(pending, ignore_errors=True)
    pending.mkdir(parents=True, exist_ok=True)

    total = 0
    try:
        # 并发下载（容器/国内网络到 clawhub 单请求可达 10-30s，串行会把
        # 安装拖到分钟级，前端 60s 超时必然断开）；并发 5 + 单文件重试 2 次
        sem = asyncio.Semaphore(5)

        async def _fetch_one(f: dict) -> None:
            nonlocal total
            rel = f["path"].lstrip("/")
            # 路径安全：拒绝绝对路径与 .. 片段，目标必须仍在 pending 内
            if not rel or ".." in Path(rel).parts:
                raise RuntimeError(f"市场文件路径可疑，拒绝: {f['path']}")
            target = (pending / rel).resolve()
            if not str(target).startswith(str(pending.resolve())):
                raise RuntimeError(f"市场文件路径可疑，拒绝: {rel}")

            data = b""
            last_err: Exception = Exception("未下载")
            for attempt in range(3):
                try:
                    data = await client.download_file(canonical_ref, rel, version=version)
                    break
                except Exception as e:  # noqa: PERF203
                    last_err = e
                    if attempt < 2:
                        await asyncio.sleep(1 + attempt)
            if not data:
                raise RuntimeError(f"下载失败 {rel}: {last_err}")

            total += len(data)
            if total > _max_total_bytes():
                raise RuntimeError("市场下载总量超过上限")
            # 清单带 sha256 时校验（防传输损坏/清单造假）
            expected = f.get("sha256") or ""
            if expected and hashlib.sha256(data).hexdigest() != expected:
                raise RuntimeError(f"文件 sha256 校验失败: {rel}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

        async def _limited(f: dict) -> None:
            async with sem:
                await _fetch_one(f)

        results = await asyncio.gather(
            *[_limited(f) for f in files], return_exceptions=True
        )
        for r in results:
            if isinstance(r, Exception):
                raise r
    except Exception as e:
        shutil.rmtree(pending, ignore_errors=True)
        return {"success": False, "skill_name": "", "installed_path": "", "version": version, "error": str(e)}

    result = _finalize_install(
        pending,
        "registry",
        url=detail.get("canonical_url", ""),
        version=version,
        installed_by="marketplace",
    )
    result["version"] = version
    return result
