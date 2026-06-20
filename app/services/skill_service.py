"""
Skill 业务逻辑层

路由层 → skill_service → SkillRegistry / SkillStateStore / DependencyInstaller

设计原则：
- 所有 MongoDB 访问都在这里（路由层禁止直接访问，符合 pre-commit 规则）
- 异步编排（registry 是同步，store/installer 是异步，这里统一协调）
- 状态变更后同步 registry 内存与持久化层
"""
import logging
from typing import Dict, List, Optional

from app.core.config import settings
from app.engine.tools.skill.availability import check_skill_dependencies
from app.engine.tools.skill.dependency_installer import install_skill_dependencies
from app.engine.tools.skill.git_installer import install_from_git, uninstall_skill
from app.engine.tools.skill.registry import SkillRegistry
from app.engine.tools.skill.state_store import SkillStateStore
from app.models.skill import (
    SkillAvailability,
    SkillInstallLog,
    SkillSummary,
)

logger = logging.getLogger(__name__)


class SkillService:
    """Skill 业务服务（无状态类，方法独立）"""

    @staticmethod
    async def _sync_disabled_to_registry() -> None:
        """从 MongoDB 加载禁用状态到 registry 内存（首次访问时）"""
        registry = SkillRegistry.get_instance()
        store = SkillStateStore()
        states = await store.load_all_states()
        disabled = {name for name, s in states.items() if not s.enabled}
        registry.set_disabled_from_store(disabled)

    @staticmethod
    async def list_skills() -> List[SkillSummary]:
        """列出所有 skill 摘要（管理界面卡片用）"""
        await SkillService._sync_disabled_to_registry()
        registry = SkillRegistry.get_instance()
        all_skills = registry.list_all_skills()

        summaries: List[SkillSummary] = []
        for meta in all_skills:
            name = meta["name"]
            availability = check_skill_dependencies(name)
            deps_total = len(availability.dependencies)
            deps_missing = sum(1 for d in availability.dependencies if not d.satisfied)

            summaries.append(
                SkillSummary(
                    name=name,
                    description=meta.get("description", ""),
                    version=meta.get("version", "0.0.0"),
                    user_invocable=meta.get("user_invocable", True),
                    enabled=registry.is_enabled(name),
                    source_type=meta.get("source_type", "local"),
                    has_scripts=meta.get("has_scripts", False),
                    has_manifest=meta.get("has_manifest", False),
                    entrypoint_count=len(registry.get_entrypoints(name)),
                    dependencies_satisfied=availability.dependencies_satisfied,
                    dependencies_total=deps_total,
                    dependencies_missing=deps_missing,
                )
            )
        return summaries

    @staticmethod
    async def get_skill_detail(name: str) -> Optional[Dict]:
        """获取单个 skill 详情"""
        await SkillService._sync_disabled_to_registry()
        registry = SkillRegistry.get_instance()

        meta = None
        for s in registry.list_all_skills():
            if s["name"] == name:
                meta = s
                break
        if meta is None:
            return None

        content = registry.get_skill_content(name)
        entrypoints = registry.get_entrypoints(name)
        availability = check_skill_dependencies(name)

        return {
            "name": name,
            "description": meta.get("description", ""),
            "version": meta.get("version", "0.0.0"),
            "user_invocable": meta.get("user_invocable", True),
            "enabled": registry.is_enabled(name),
            "source_type": meta.get("source_type", "local"),
            "has_scripts": meta.get("has_scripts", False),
            "has_manifest": meta.get("has_manifest", False),
            "path": meta.get("path", ""),
            "skill_dir": meta.get("skill_dir", ""),
            "entrypoints": entrypoints,
            "availability": availability.model_dump(),
            "content_preview": (content[:500] + "...") if content and len(content) > 500 else content,
        }

    @staticmethod
    async def get_skill_content(name: str) -> Optional[str]:
        """获取 SKILL.md 完整原文"""
        await SkillService._sync_disabled_to_registry()
        registry = SkillRegistry.get_instance()
        return registry.get_skill_content(name)

    @staticmethod
    async def toggle_skill(name: str, enabled: bool, username: str = "user") -> Dict:
        """启停 skill（持久化）"""
        registry = SkillRegistry.get_instance()
        store = SkillStateStore()

        if enabled:
            ok = registry.enable_skill(name)
        else:
            ok = registry.disable_skill(name)

        if not ok:
            return {"success": False, "error": f"skill 不存在: {name}"}

        await store.set_enabled(name, enabled)
        logger.info(f"[SkillService] {username} {'启用' if enabled else '禁用'} skill: {name}")
        return {"success": True, "enabled": enabled, "name": name}

    @staticmethod
    async def check_skill(name: str) -> SkillAvailability:
        """检查依赖状态（不安装）"""
        await SkillService._sync_disabled_to_registry()
        return check_skill_dependencies(name)

    @staticmethod
    async def install_skill_deps(name: str, username: str = "user") -> Dict:
        """手动触发依赖安装（绕过全局开关的限制由用户意图保证）"""
        await SkillService._sync_disabled_to_registry()
        result = await install_skill_dependencies(
            name, installed_by=f"user:{username}"
        )
        return result

    @staticmethod
    async def reload_skills() -> Dict:
        """重新扫描目录 + 重建工具"""
        registry = SkillRegistry.get_instance()
        skills = registry.reload()

        # 重新注册 entrypoints
        try:
            from app.engine.tools.skill.entrypoint_loader import (
                load_all_skill_entrypoints,
            )
            load_all_skill_entrypoints()
        except Exception as e:
            logger.warning(f"reload 后重注册 entrypoints 失败: {e}")

        return {
            "success": True,
            "total": len(skills),
            "names": [s["name"] for s in skills],
        }

    @staticmethod
    async def install_from_git(
        url: str,
        trusted_hosts: Optional[List[str]] = None,
        username: str = "user",
    ) -> Dict:
        """从 Git URL 安装"""
        result = install_from_git(url, trusted_hosts_override=trusted_hosts)
        if result["success"]:
            # 安装后触发依赖自动安装
            skill_name = result["skill_name"]
            try:
                dep_result = await install_skill_dependencies(
                    skill_name, installed_by=f"user:{username}"
                )
                result["dependency_install"] = dep_result
            except Exception as e:
                logger.warning(f"Git 安装后依赖自动安装失败: {e}")
                result["dependency_install"] = {"error": str(e)}
        return result

    @staticmethod
    async def install_from_registry(
        name: str,
        version: Optional[str] = None,
        username: str = "user",
    ) -> Dict:
        """从中心化注册表安装（本期未实现，返回 501 信息）"""
        registry_url = getattr(settings, "SKILL_REGISTRY_URL", "")
        if not registry_url:
            return {
                "success": False,
                "error": "中心化注册表未配置（SKILL_REGISTRY_URL 为空），本期不支持",
                "hint": "请使用本地放置或 Git URL 安装",
            }
        return {
            "success": False,
            "error": f"注册表功能尚未实现（SKILL_REGISTRY_URL={registry_url}）",
        }

    @staticmethod
    async def uninstall(name: str, force: bool = False, username: str = "user") -> Dict:
        """卸载 skill"""
        result = uninstall_skill(name, force=force)
        if result["success"]:
            logger.info(f"[SkillService] {username} 卸载 skill: {name}")
        return result

    @staticmethod
    async def list_install_logs(
        skill_name: Optional[str] = None,
        limit: int = 100,
    ) -> List[SkillInstallLog]:
        """查询安装审计日志"""
        store = SkillStateStore()
        return await store.list_install_logs(skill_name=skill_name, limit=limit)

    @staticmethod
    async def get_global_config() -> Dict:
        """获取 skill 系统的全局配置（前端展示用）"""
        return {
            "auto_install": getattr(settings, "SKILL_AUTO_INSTALL", True),
            "allowed_packages": [
                p.strip()
                for p in getattr(settings, "SKILL_ALLOWED_PACKAGES", "").split(",")
                if p.strip()
            ],
            "install_timeout": getattr(settings, "SKILL_INSTALL_TIMEOUT", 300),
            "registry_url": getattr(settings, "SKILL_REGISTRY_URL", ""),
            "git_trusted_hosts": [
                h.strip()
                for h in getattr(settings, "SKILL_GIT_TRUSTED_HOSTS", "").split(",")
                if h.strip()
            ],
        }
