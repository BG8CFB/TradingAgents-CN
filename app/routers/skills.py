"""
Skill 管理 API 路由

prefix=/api/skills，tags=["Skills"]
所有 MongoDB 访问通过 SkillService（不直接访问 DB，遵守 no-mongo-in-routers 规则）。

路由注册顺序约束：固定路径（install/*、marketplace/* 等）必须注册在
/{skill_name} 之前，否则会被 path 参数吞掉。
"""
import asyncio
import logging
import tempfile
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Path as FastAPIPath, UploadFile
from pydantic import BaseModel, Field

from app.core.config import settings
from app.engine.tools.skill.marketplace import MarketplaceRateLimited
from app.routers.auth_db import get_current_user, require_admin
from app.services.skill_service import SkillService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/skills", tags=["Skills"])


# ──────────────────────────────────────────────────────────────────────
# 请求/响应模型
# ──────────────────────────────────────────────────────────────────────


class ToggleRequest(BaseModel):
    enabled: bool = Field(..., description="是否启用")


class GitInstallRequest(BaseModel):
    url: str = Field(..., description="Git URL（仅 https）")
    trusted_hosts: Optional[List[str]] = Field(
        default=None,
        description="（已弃用）临时可信主机；管理员提交 URL 即授权该主机，无需填写",
    )


class RegistryInstallRequest(BaseModel):
    name: str = Field(..., description="市场 skill 标识（slug）")
    version: Optional[str] = Field(default=None, description="版本（空表示最新）")


class LocalPathInstallRequest(BaseModel):
    path: str = Field(..., description="服务器上的 skill 目录绝对路径（须含 SKILL.md）")


class ReferenceInstallRequest(BaseModel):
    reference: str = Field(
        ...,
        description=(
            "安装引用或完整安装命令，支持：openclaw skills install X / "
            "@owner/slug / skills-sh:owner/repo/subdir / git:owner/repo / "
            "https://...[#subdir]"
        ),
    )


class UninstallRequest(BaseModel):
    force: bool = Field(default=False, description="是否强制卸载本地 skill")


# ──────────────────────────────────────────────────────────────────────
# 固定路径路由（必须在 /{skill_name} 之前注册）
# ──────────────────────────────────────────────────────────────────────


@router.get("")
async def list_skills(user: dict = Depends(get_current_user)):
    """列出全部 skill"""
    skills = await SkillService.list_skills()
    # 统一 ApiResponse 形状：前端 store/拦截器按 success+data 判断，裸 dict 会被静默丢弃
    return {
        "success": True,
        "data": {"skills": [s.model_dump() for s in skills], "total": len(skills)},
    }


@router.get("/config")
async def get_skill_config(user: dict = Depends(get_current_user)):
    """获取全局 skill 系统配置"""
    return {"success": True, "data": await SkillService.get_global_config()}


@router.get("/install-logs")
async def list_install_logs(
    skill_name: Optional[str] = None,
    limit: int = 100,
    kind: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    """查询安装审计日志（kind: skill | mcp，缺省全部）"""
    logs = await SkillService.list_install_logs(skill_name=skill_name, limit=limit, kind=kind)
    return {
        "success": True,
        "data": {
            "logs": [log.model_dump(by_alias=False) for log in logs],
            "total": len(logs),
        },
    }


@router.post("/reload")
async def reload_skills(user: dict = Depends(require_admin)):
    """重新扫描 skill 目录（仅管理员）"""
    return {"success": True, "data": await SkillService.reload_skills()}


@router.post("/install/git")
async def install_from_git(
    payload: GitInstallRequest,
    user: dict = Depends(require_admin),
):
    """从 Git URL 安装 skill（仅管理员；URL 主机自动可信，无需填临时可信主机）"""
    username = user.get("username", "user") if isinstance(user, dict) else "user"
    result = await SkillService.install_from_git(
        payload.url, payload.trusted_hosts, username
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@router.post("/install/registry")
async def install_from_registry(
    payload: RegistryInstallRequest,
    user: dict = Depends(require_admin),
):
    """从 ClawHub 市场一键安装（仅管理员；name 为市场 slug）"""
    username = user.get("username", "user") if isinstance(user, dict) else "user"
    result = await SkillService.install_from_registry(
        payload.name, payload.version, username
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


# ── 安装后台任务（慢网下市场/Git 下载可达分钟级，同步等待会拖死前端，改为提交后轮询） ──

# 进程内任务表：{task_id: {"status": "running"|"done", "reference": str, "result": dict}}
_install_tasks: dict = {}


@router.post("/install/reference")
async def install_from_reference(
    payload: ReferenceInstallRequest,
    user: dict = Depends(require_admin),
):
    """按安装命令/引用一键安装（仅管理员；后台执行，返回 task_id 供轮询）"""
    username = user.get("username", "user") if isinstance(user, dict) else "user"
    task_id = uuid.uuid4().hex[:12]
    _install_tasks[task_id] = {"status": "running", "reference": payload.reference, "result": None}

    async def _run():
        try:
            result = await SkillService.install_from_reference(payload.reference, username)
        except Exception as e:  # 兜底：任务内异常不能没人接
            result = {"success": False, "skill_name": "", "installed_path": "", "error": str(e)}
        _install_tasks[task_id] = {
            "status": "done",
            "reference": payload.reference,
            "result": result,
        }

    asyncio.create_task(_run())
    # ApiResponse 形状（success+data）：store 通过 data.task_id 取任务号后进入轮询
    return {
        "success": True,
        "data": {"task_id": task_id, "status": "running"},
    }


@router.get("/install/reference/{task_id}")
async def install_reference_status(
    task_id: str,
    user: dict = Depends(require_admin),
):
    """查询粘贴命令安装任务的结果"""
    task = _install_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="安装任务不存在或已过期")
    return {"success": True, "data": task}


@router.post("/install/local-path")
async def install_from_local_path(
    payload: LocalPathInstallRequest,
    user: dict = Depends(require_admin),
):
    """从服务器本地目录导入 skill（仅管理员）"""
    username = user.get("username", "user") if isinstance(user, dict) else "user"
    result = await SkillService.install_from_local_path(payload.path, username)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@router.post("/install/upload")
async def install_from_upload(
    file: UploadFile = File(...),
    user: dict = Depends(require_admin),
):
    """上传 zip 包安装 skill（仅管理员）"""
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="仅支持 .zip 文件")

    username = user.get("username", "user") if isinstance(user, dict) else "user"
    max_mb = int(getattr(settings, "SKILL_UPLOAD_MAX_SIZE_MB", 20))
    limit = max_mb * 1024 * 1024

    # 流式落盘到临时文件（边写边校验大小）
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    try:
        written = 0
        while chunk := await file.read(1024 * 1024):
            written += len(chunk)
            if written > limit:
                raise HTTPException(
                    status_code=413, detail=f"上传超过大小上限（{max_mb}MB）"
                )
            tmp.write(chunk)
        tmp.close()
        result = await SkillService.install_from_zip(tmp.name, username)
    finally:
        tmp.close()
        Path(tmp.name).unlink(missing_ok=True)

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


# ── ClawHub 市场只读代理（登录即可，无条件启用） ──────────────────────


def _translate_marketplace_error(e: Exception) -> HTTPException:
    if isinstance(e, MarketplaceRateLimited):
        http_error = HTTPException(
            status_code=429,
            detail=f"市场限流，请在 {e.retry_after} 秒后重试",
        )
        http_error.headers = {"Retry-After": str(e.retry_after)}
        return http_error
    return HTTPException(status_code=502, detail=str(e)[:300])


@router.get("/marketplace/skills")
async def marketplace_list(
    limit: int = 60,
    cursor: str = "",
    sort: str = "",
    user: dict = Depends(get_current_user),
):
    """市场技能列表（分页）"""
    try:
        return await SkillService.marketplace_list(limit=limit, cursor=cursor, sort=sort)
    except Exception as e:
        raise _translate_marketplace_error(e)


@router.get("/marketplace/search")
async def marketplace_search(
    q: str,
    user: dict = Depends(get_current_user),
):
    """市场技能搜索"""
    try:
        return await SkillService.marketplace_search(q)
    except Exception as e:
        raise _translate_marketplace_error(e)


@router.get("/marketplace/skills/{slug}")
async def marketplace_detail(
    slug: str,
    user: dict = Depends(get_current_user),
):
    """市场技能详情（含 SKILL.md 与 canonical 链接）"""
    try:
        return await SkillService.marketplace_detail(slug)
    except Exception as e:
        raise _translate_marketplace_error(e)


# ──────────────────────────────────────────────────────────────────────
# 动态路径路由（/{skill_name}，必须最后注册）
# ──────────────────────────────────────────────────────────────────────


@router.get("/{skill_name}")
async def get_skill_detail(
    skill_name: str = FastAPIPath(..., description="skill 名"),
    user: dict = Depends(get_current_user),
):
    """获取单个 skill 详情"""
    detail = await SkillService.get_skill_detail(skill_name)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"skill 不存在: {skill_name}")
    return {"success": True, "data": detail}


@router.get("/{skill_name}/content")
async def get_skill_content(
    skill_name: str = FastAPIPath(..., description="skill 名"),
    user: dict = Depends(get_current_user),
):
    """获取 SKILL.md 完整原文（前端 markdown 渲染用）"""
    content = await SkillService.get_skill_content(skill_name)
    if content is None:
        raise HTTPException(status_code=404, detail=f"skill 不存在或已禁用: {skill_name}")
    return {"success": True, "data": {"name": skill_name, "content": content}}


@router.post("/{skill_name}/toggle")
async def toggle_skill(
    payload: ToggleRequest,
    skill_name: str = FastAPIPath(..., description="skill 名"),
    user: dict = Depends(get_current_user),
):
    """启停 skill"""
    username = user.get("username", "user") if isinstance(user, dict) else "user"
    result = await SkillService.toggle_skill(skill_name, payload.enabled, username)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error"))
    return result


@router.post("/{skill_name}/check")
async def check_skill(
    skill_name: str = FastAPIPath(..., description="skill 名"),
    user: dict = Depends(get_current_user),
):
    """检查 skill 依赖状态（不安装）"""
    availability = await SkillService.check_skill(skill_name)
    return {"success": True, "data": availability.model_dump()}


@router.post("/{skill_name}/install")
async def install_skill_deps(
    skill_name: str = FastAPIPath(..., description="skill 名"),
    user: dict = Depends(get_current_user),
):
    """手动触发依赖安装"""
    username = user.get("username", "user") if isinstance(user, dict) else "user"
    result = await SkillService.install_skill_deps(skill_name, username)
    return result


@router.delete("/{skill_name}")
async def uninstall_skill_route(
    skill_name: str = FastAPIPath(..., description="skill 名"),
    force: bool = False,
    user: dict = Depends(require_admin),
):
    """卸载 skill（仅管理员；本地 skill 需 force=true）"""
    username = user.get("username", "user") if isinstance(user, dict) else "user"
    result = await SkillService.uninstall(skill_name, force=force, username=username)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result
