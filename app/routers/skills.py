"""
Skill 管理 API 路由

prefix=/api/skills，tags=["Skills"]
所有 MongoDB 访问通过 SkillService（不直接访问 DB，遵守 no-mongo-in-routers 规则）。
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path as FastAPIPath
from pydantic import BaseModel, Field

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
    url: str = Field(..., description="Git URL（https/ssh）")
    trusted_hosts: Optional[List[str]] = Field(
        default=None,
        description="临时可信主机覆盖（与全局 SKILL_GIT_TRUSTED_HOSTS 合并）",
    )


class RegistryInstallRequest(BaseModel):
    name: str = Field(..., description="skill 名")
    version: Optional[str] = Field(default=None, description="版本（空表示最新）")


class UninstallRequest(BaseModel):
    force: bool = Field(default=False, description="是否强制卸载本地 skill")


# ──────────────────────────────────────────────────────────────────────
# 路由
# ──────────────────────────────────────────────────────────────────────


@router.get("")
async def list_skills(user: dict = Depends(get_current_user)):
    """列出全部 skill"""
    skills = await SkillService.list_skills()
    return {"skills": [s.model_dump() for s in skills], "total": len(skills)}


@router.get("/config")
async def get_skill_config(user: dict = Depends(get_current_user)):
    """获取全局 skill 系统配置"""
    return await SkillService.get_global_config()


@router.get("/install-logs")
async def list_install_logs(
    skill_name: Optional[str] = None,
    limit: int = 100,
    user: dict = Depends(get_current_user),
):
    """查询安装审计日志"""
    logs = await SkillService.list_install_logs(skill_name=skill_name, limit=limit)
    return {
        "logs": [log.model_dump(by_alias=False) for log in logs],
        "total": len(logs),
    }


@router.get("/{skill_name}")
async def get_skill_detail(
    skill_name: str = FastAPIPath(..., description="skill 名"),
    user: dict = Depends(get_current_user),
):
    """获取单个 skill 详情"""
    detail = await SkillService.get_skill_detail(skill_name)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"skill 不存在: {skill_name}")
    return detail


@router.get("/{skill_name}/content")
async def get_skill_content(
    skill_name: str = FastAPIPath(..., description="skill 名"),
    user: dict = Depends(get_current_user),
):
    """获取 SKILL.md 完整原文（前端 markdown 渲染用）"""
    content = await SkillService.get_skill_content(skill_name)
    if content is None:
        raise HTTPException(status_code=404, detail=f"skill 不存在或已禁用: {skill_name}")
    return {"name": skill_name, "content": content}


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
    return availability.model_dump()


@router.post("/{skill_name}/install")
async def install_skill_deps(
    skill_name: str = FastAPIPath(..., description="skill 名"),
    user: dict = Depends(get_current_user),
):
    """手动触发依赖安装"""
    username = user.get("username", "user") if isinstance(user, dict) else "user"
    result = await SkillService.install_skill_deps(skill_name, username)
    return result


@router.post("/reload")
async def reload_skills(user: dict = Depends(require_admin)):
    """重新扫描 skill 目录（仅管理员）"""
    return await SkillService.reload_skills()


@router.post("/install/git")
async def install_from_git(
    payload: GitInstallRequest,
    user: dict = Depends(get_current_user),
):
    """从 Git URL 安装 skill"""
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
    user: dict = Depends(get_current_user),
):
    """从中心化注册表安装（本期未实现）"""
    username = user.get("username", "user") if isinstance(user, dict) else "user"
    result = await SkillService.install_from_registry(
        payload.name, payload.version, username
    )
    if not result.get("success"):
        raise HTTPException(status_code=501, detail=result.get("error"))
    return result


@router.delete("/{skill_name}")
async def uninstall_skill_route(
    skill_name: str = FastAPIPath(..., description="skill 名"),
    force: bool = False,
    user: dict = Depends(get_current_user),
):
    """卸载 skill（本地 skill 需 force=true）"""
    username = user.get("username", "user") if isinstance(user, dict) else "user"
    result = await SkillService.uninstall(skill_name, force=force, username=username)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result
