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
from app.engine.tools.skill.git_installer import (
    install_from_git_interactive,
    uninstall_skill,
)
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
    def resolve_install_reference(reference: str) -> Dict:
        """
        解析安装引用/安装命令为可执行的安装动作。

        支持格式（对齐 openclaw CLI 的安装命令）：
        - "https://github.com/user/repo(.git)"            → git 安装
        - "https://...#subdir"                            → git 安装（子目录为 skill 根）
        - "skills-sh:owner/repo/subdir"                   → git 安装 github.com/owner/repo 的 subdir
        - "git:owner/repo[@ref]"                          → git 安装 github.com/owner/repo
        - "@owner/slug" / "owner/slug" / "slug"           → ClawHub 市场安装
        - "openclaw skills install <以上任意一种>"        → 剥掉命令外壳后同样处理

        Returns:
            {"kind": "git"|"marketplace", "url": str, "subdir": str, "reference": str}
            解析失败时 {"kind": "invalid", "error": str}
        """
        text = (reference or "").strip()
        if not text:
            return {"kind": "invalid", "error": "安装引用为空"}

        # 剥掉安装命令外壳：openclaw/clawhub/skills CLI 的 install/add 命令
        for cmd in (
            "openclaw skills install",
            "clawhub install",
            "skills install",
            "npx skills add",
            "skills add",
        ):
            if text.lower().startswith(cmd):
                text = text[len(cmd):].strip()
                break
        text = text.strip().strip("\"'`")

        if text.startswith(("https://", "http://")):
            # ClawHub 市场页面 URL（https://clawhub.ai/{owner}/skills/{slug}）
            # → 转为市场引用安装，不能走 git clone
            market_ref = SkillService._parse_marketplace_url(text)
            if market_ref:
                return {"kind": "marketplace", "url": "", "subdir": "", "reference": market_ref}
            # 普通 Git URL；fragment 作为子目录（monorepo 场景）
            url, _, frag = text.partition("#")
            return {"kind": "git", "url": url, "subdir": frag.strip("/"), "reference": url}

        if text.startswith("skills-sh:"):
            parts = text[len("skills-sh:"):].strip("/").split("/")
            if len(parts) < 2:
                return {"kind": "invalid", "error": f"skills-sh 引用格式应为 owner/repo[/subdir]: {text}"}
            owner, repo = parts[0], parts[1]
            subdir = "/".join(parts[2:])
            return {
                "kind": "git",
                "url": f"https://github.com/{owner}/{repo}.git",
                "subdir": subdir,
                "reference": text,
            }

        if text.startswith("git:"):
            body = text[len("git:"):]
            # git:owner/repo@ref → 忽略 ref（--depth 1 默认 HEAD）
            body = body.split("@")[0] if "@" in body else body
            parts = body.strip("/").split("/")
            if len(parts) < 2:
                return {"kind": "invalid", "error": f"git 引用格式应为 owner/repo: {text}"}
            return {
                "kind": "git",
                "url": f"https://github.com/{parts[0]}/{parts[1]}.git",
                "subdir": "/".join(parts[2:]),
                "reference": text,
            }

        # 其余按市场引用处理（@owner/slug、owner/slug、裸 slug）
        return {"kind": "marketplace", "url": "", "subdir": "", "reference": text.lstrip("@")}

    @staticmethod
    def _parse_marketplace_url(text: str) -> Optional[str]:
        """
        识别市场 canonical 页面 URL 并提取 owner/slug 引用。

        匹配 https://clawhub.ai/{owner}/skills/{slug}（host 需与
        SKILL_MARKETPLACE_URL 一致，避免误吞其他站点）；不匹配返回 None。
        """
        host = SkillService._marketplace_url().split("//")[-1].split("/")[0].lower()
        prefix = f"https://{host}/"
        if not text.lower().startswith(prefix):
            return None
        parts = text[len(prefix):].split("?")[0].strip("/").split("/")
        # {owner}/skills/{slug}
        if len(parts) == 3 and parts[1] == "skills" and parts[0] and parts[2]:
            return f"{parts[0]}/{parts[2]}"
        return None

    @staticmethod
    async def install_from_reference(reference: str, username: str = "user") -> Dict:
        """按解析结果路由到 git / 市场安装（前端"粘贴安装命令"入口）"""
        resolved = SkillService.resolve_install_reference(reference)
        if resolved["kind"] == "invalid":
            return {"success": False, "skill_name": "", "installed_path": "", "error": resolved["error"]}
        if resolved["kind"] == "git":
            return await SkillService.install_from_git(
                resolved["url"], username=username, subdir=resolved["subdir"] or None
            )
        return await SkillService.install_from_registry(resolved["reference"], username=username)

    @staticmethod
    async def install_from_git(
        url: str,
        trusted_hosts: Optional[List[str]] = None,
        username: str = "user",
        subdir: Optional[str] = None,
    ) -> Dict:
        """从 Git URL 安装（trusted_hosts 已弃用：管理员提交 URL 即授权该主机）"""
        if trusted_hosts:
            logger.warning("[SkillService] trusted_hosts 参数已弃用，提交的 URL 主机自动可信")
        result = install_from_git_interactive(url, subdir=subdir)
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
    async def install_from_local_path(path: str, username: str = "user") -> Dict:
        """从服务器本地目录导入 skill"""
        from app.engine.tools.skill.local_installer import install_from_local_path

        result = install_from_local_path(path)
        if result["success"]:
            try:
                dep_result = await install_skill_dependencies(
                    result["skill_name"], installed_by=f"user:{username}"
                )
                result["dependency_install"] = dep_result
            except Exception as e:
                logger.warning(f"本地导入后依赖自动安装失败: {e}")
                result["dependency_install"] = {"error": str(e)}
        return result

    @staticmethod
    async def install_from_zip(zip_path, username: str = "user") -> Dict:
        """从上传的 zip 包安装 skill"""
        from app.engine.tools.skill.local_installer import install_from_zip

        result = install_from_zip(zip_path)
        if result["success"]:
            try:
                dep_result = await install_skill_dependencies(
                    result["skill_name"], installed_by=f"user:{username}"
                )
                result["dependency_install"] = dep_result
            except Exception as e:
                logger.warning(f"zip 安装后依赖自动安装失败: {e}")
                result["dependency_install"] = {"error": str(e)}
        return result

    @staticmethod
    async def install_from_registry(
        name: str,
        version: Optional[str] = None,
        username: str = "user",
    ) -> Dict:
        """从 ClawHub 市场安装（name 为市场 slug）"""
        from app.engine.tools.skill.registry_installer import install_from_marketplace

        result = await install_from_marketplace(name, version=version)
        if result["success"]:
            try:
                dep_result = await install_skill_dependencies(
                    result["skill_name"], installed_by=f"user:{username}"
                )
                result["dependency_install"] = dep_result
            except Exception as e:
                logger.warning(f"市场安装后依赖自动安装失败: {e}")
                result["dependency_install"] = {"error": str(e)}
        return result

    # ── ClawHub 市场只读代理（无条件启用，地址由 SKILL_MARKETPLACE_URL 控制） ──

    @staticmethod
    def _marketplace_url() -> str:
        url = getattr(settings, "SKILL_MARKETPLACE_URL", "") or ""
        if not url:
            url = getattr(settings, "SKILL_REGISTRY_URL", "") or ""
        return url.rstrip("/")

    @staticmethod
    async def marketplace_list(limit: int = 60, cursor: str = "", sort: str = "") -> Dict:
        from app.engine.tools.skill.marketplace import get_marketplace_client

        client = get_marketplace_client(SkillService._marketplace_url())
        return await client.list_skills(limit=limit, cursor=cursor, sort=sort)

    @staticmethod
    async def marketplace_search(q: str) -> Dict:
        from app.engine.tools.skill.marketplace import get_marketplace_client

        client = get_marketplace_client(SkillService._marketplace_url())
        return await client.search(q)

    @staticmethod
    async def marketplace_detail(slug: str) -> Dict:
        from app.engine.tools.skill.marketplace import get_marketplace_client

        client = get_marketplace_client(SkillService._marketplace_url())
        detail = await client.get_skill(slug)
        # 标记本地是否已安装（前端置灰用）
        installed_names = {s["name"] for s in SkillRegistry.get_instance().list_all_skills()}
        detail["installed"] = detail.get("name") in installed_names or slug in installed_names
        return detail

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
        kind: Optional[str] = None,
    ) -> List[SkillInstallLog]:
        """查询安装审计日志（kind: skill | mcp，None 表示全部）"""
        store = SkillStateStore()
        return await store.list_install_logs(skill_name=skill_name, limit=limit, kind=kind)

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
            "marketplace_url": SkillService._marketplace_url(),
            "git_trusted_hosts": [
                h.strip()
                for h in getattr(settings, "SKILL_GIT_TRUSTED_HOSTS", "").split(",")
                if h.strip()
            ],
        }
