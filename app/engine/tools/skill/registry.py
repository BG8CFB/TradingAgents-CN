"""
Skill 注册表

管理技能的发现、加载、启停状态、依赖检查。
单例模式，扫描多个目录：
- 用户本地 config/skills/（最高优先级）
- Git/registry 缓存 config/skills/.cache/
- 内置示例 app/engine/tools/skill/builtin/

启动时自动发现；运行时支持 reload、enable/disable、ensure_dependencies。
启停状态通过 SkillStateStore 持久化到 MongoDB，避免重启后丢失。
"""
import logging
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional

from app.engine.tools.skill.loader import (
    get_builtin_skills_dir,
    get_cache_skills_dir,
    get_default_user_skills_dir,
    load_skill_content,
    parse_skill_metadata,
)
from app.engine.tools.skill.manifest import load_manifest
from app.models.skill import SkillManifest

logger = logging.getLogger(__name__)


class SkillRegistry:
    """
    技能注册表（单例）

    职责：
    - 扫描多个目录，发现所有已安装的 Skill
    - 缓存 SKILL.md 内容与 manifest，避免重复 I/O
    - 管理启停状态（持久化到 MongoDB）
    - 暴露 ensure_dependencies 接口供 ToolRegistry 调用（首次加载自动安装）
    """

    _instance: Optional["SkillRegistry"] = None
    _lock = threading.Lock()

    def __init__(self, skills_dir: Optional[str] = None):
        """
        初始化注册表（建议通过 get_instance() 获取单例）

        Args:
            skills_dir: 显式指定用户 skill 目录（测试用）；默认 config/skills
        """
        self._user_skills_dir = skills_dir or get_default_user_skills_dir()
        self._cache_skills_dir = get_cache_skills_dir()
        self._builtin_skills_dir = get_builtin_skills_dir()

        # 已发现的 skill 元数据列表
        self._skills: List[Dict] = []
        # skill_name → manifest（仅带 manifest 的 skill 才有）
        self._manifests: Dict[str, SkillManifest] = {}
        # skill_name → 禁用状态（内存副本，启动时从 MongoDB 加载）
        self._disabled: set = set()
        # skill_name → SKILL.md 内容缓存
        self._content_cache: Dict[str, str] = {}

        # 依赖检查与安装回调（由 ToolRegistry 在 initialize 时注入，避免循环导入）
        self._dependency_check_callback: Optional[Callable[[str], Dict]] = None
        self._dependency_install_callback: Optional[Callable[[str], Dict]] = None

        # MongoDB 状态已加载标志（首次访问异步方法时加载）
        self._state_loaded: bool = False
        self._state_lock = threading.Lock()

        # 启动时自动发现
        self.discover_skills()

    @classmethod
    def get_instance(cls) -> "SkillRegistry":
        """获取全局单例"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（测试用）"""
        with cls._lock:
            cls._instance = None

    def set_dependency_callbacks(
        self,
        check_callback: Optional[Callable[[str], Dict]] = None,
        install_callback: Optional[Callable[[str], Dict]] = None,
    ) -> None:
        """
        注入依赖检查与安装回调（由 ToolRegistry 注入，避免循环导入）

        Args:
            check_callback: async/sync 函数，参数 skill_name，返回 {satisfied, missing, ...}
            install_callback: async/sync 函数，参数 skill_name，返回安装结果
        """
        self._dependency_check_callback = check_callback
        self._dependency_install_callback = install_callback

    def discover_skills(self) -> List[Dict]:
        """
        扫描所有 skill 目录，发现已安装的 Skill

        扫描顺序：用户本地 → 缓存 → 内置。同名时先发现的优先（用户覆盖内置）。

        Returns:
            技能元数据列表
        """
        discovered: List[Dict] = []
        seen_names: set = set()

        for base_dir in [
            self._user_skills_dir,
            self._cache_skills_dir,
            self._builtin_skills_dir,
        ]:
            base = Path(base_dir)
            if not base.exists():
                continue

            # 1. 子目录模式：{dir}/{name}/SKILL.md
            try:
                for subdir in sorted(base.iterdir()):
                    if not subdir.is_dir():
                        continue
                    # 跳过缓存子目录自身（避免递归扫描 .cache）
                    if subdir.name == ".cache" and base_dir == self._user_skills_dir:
                        continue
                    skill_md = subdir / "SKILL.md"
                    if not skill_md.exists():
                        continue

                    meta = parse_skill_metadata(str(skill_md))
                    name = meta.get("name")
                    if not name or name in seen_names:
                        continue

                    seen_names.add(name)

                    # 解析 manifest（可选）
                    skill_dir = str(subdir.resolve())
                    manifest = load_manifest(skill_dir)
                    if manifest is not None:
                        self._manifests[name] = manifest

                    discovered.append(
                        {
                            "name": name,
                            "description": meta.get("description", ""),
                            "version": meta.get("version", "0.0.0"),
                            "user_invocable": meta.get("user_invocable", True),
                            "path": str(skill_md.resolve()),
                            "skill_dir": skill_dir,
                            "has_manifest": manifest is not None,
                            "has_scripts": (subdir / "scripts").is_dir(),
                            "source_type": self._classify_source_dir(base_dir),
                        }
                    )
            except Exception as e:
                logger.warning(f"扫描 skill 目录失败 {base_dir}: {e}")

            # 2. 扁平模式：{dir}/{name}.md
            try:
                for md_file in sorted(base.glob("*.md")):
                    if md_file.name.upper() == "SKILL.MD":
                        continue
                    if not md_file.is_file():
                        continue

                    meta = parse_skill_metadata(str(md_file))
                    name = meta.get("name")
                    if not name or name in seen_names:
                        continue

                    seen_names.add(name)
                    discovered.append(
                        {
                            "name": name,
                            "description": meta.get("description", ""),
                            "version": meta.get("version", "0.0.0"),
                            "user_invocable": meta.get("user_invocable", True),
                            "path": str(md_file.resolve()),
                            "skill_dir": str(md_file.parent.resolve()),
                            "has_manifest": False,
                            "has_scripts": False,
                            "source_type": self._classify_source_dir(base_dir),
                        }
                    )
            except Exception as e:
                logger.warning(f"扫描扁平 skill 失败 {base_dir}: {e}")

        self._skills = discovered
        # 清除内容缓存（目录可能已变化）
        self._content_cache.clear()

        logger.info(
            f"技能发现完成: 共发现 {len(discovered)} 个技能"
            f"（含 manifest={len(self._manifests)}）"
        )
        return self._skills

    def _classify_source_dir(self, base_dir: str) -> str:
        """根据目录位置判断 source_type"""
        if base_dir == self._user_skills_dir:
            return "local"
        if base_dir == self._cache_skills_dir:
            return "git"  # 或 registry，运行时由 manifest.source.type 细化
        if base_dir == self._builtin_skills_dir:
            return "builtin"
        return "local"

    def get_skill_dir(self, name: str) -> Optional[str]:
        """获取 skill 的根目录路径"""
        for s in self._skills:
            if s["name"] == name:
                return s.get("skill_dir")
        return None

    def get_manifest(self, name: str) -> Optional[SkillManifest]:
        """获取 skill 的 manifest（无 manifest 时返回 None）"""
        return self._manifests.get(name)

    def get_entrypoints(self, name: str) -> List[Dict]:
        """
        获取 skill 暴露的脚本入口列表

        Returns:
            入口字典列表（每个含 name/display_name/description/module/function 等）
        """
        manifest = self._manifests.get(name)
        if manifest is None:
            return []
        return [ep.model_dump(by_alias=True) for ep in manifest.entrypoints]

    def get_skill_content(self, name: str) -> Optional[str]:
        """
        获取指定技能的 SKILL.md 完整内容（带缓存）

        Args:
            name: 技能名称

        Returns:
            SKILL.md 的完整文本，未找到或已禁用时返回 None
        """
        if not self.is_enabled(name):
            logger.warning(f"技能已禁用: {name}")
            return None

        if name in self._content_cache:
            return self._content_cache[name]

        # 从已发现的 path 直接读取（比 _resolve_skill_path 更快）
        skill_path = None
        for s in self._skills:
            if s["name"] == name:
                skill_path = s.get("path")
                break

        if skill_path is None:
            # 兜底：通过 loader 解析
            content = load_skill_content(name, self._user_skills_dir)
        else:
            try:
                content = Path(skill_path).read_text(encoding="utf-8")
            except Exception as e:
                logger.error(f"读取技能内容失败 {name}: {e}")
                content = None

        if content is not None:
            self._content_cache[name] = content

        return content

    def list_skills(self) -> List[Dict]:
        """
        列出所有已启用且用户可调用的技能（用于 load_skill 工具描述）

        Returns:
            技能摘要列表，每项包含 name 和 description
        """
        return [
            {"name": s["name"], "description": s["description"]}
            for s in self._skills
            if s.get("user_invocable", True) and s["name"] not in self._disabled
        ]

    def list_all_skills(self) -> List[Dict]:
        """
        列出全部 skill（含禁用、依赖未满足），用于管理界面

        Returns:
            全部 skill 的元数据字典
        """
        return list(self._skills)

    def enable_skill(self, name: str) -> bool:
        """
        启用指定技能（同步：更新内存；异步持久化由调用方处理）

        Args:
            name: 技能名称

        Returns:
            操作是否成功（技能是否存在）
        """
        skill_names = {s["name"] for s in self._skills}
        if name not in skill_names:
            logger.warning(f"尝试启用不存在的技能: {name}")
            return False

        self._disabled.discard(name)
        self._content_cache.pop(name, None)
        logger.info(f"技能已启用: {name}")
        return True

    def disable_skill(self, name: str) -> bool:
        """
        禁用指定技能（同步：更新内存）

        Args:
            name: 技能名称

        Returns:
            操作是否成功（技能是否存在）
        """
        skill_names = {s["name"] for s in self._skills}
        if name not in skill_names:
            logger.warning(f"尝试禁用不存在的技能: {name}")
            return False

        self._disabled.add(name)
        logger.info(f"技能已禁用: {name}")
        return True

    def set_disabled_from_store(self, disabled_names: set) -> None:
        """
        从持久化层加载禁用状态（启动时由 ToolRegistry 注入）

        Args:
            disabled_names: 已禁用的 skill 名集合
        """
        self._disabled = set(disabled_names)

    def is_enabled(self, name: str) -> bool:
        """检查指定技能是否启用"""
        skill_names = {s["name"] for s in self._skills}
        return name in skill_names and name not in self._disabled

    def check_dependencies(self, name: str) -> Dict:
        """
        检查 skill 的依赖是否满足（不安装）

        若注入了 dependency_check_callback 则调用它；否则只做基础检查
        （无 manifest 的 skill 默认满足）。

        Returns:
            {
                "satisfied": bool,
                "missing": List[str],
                "warnings": List[str],
            }
        """
        if self._dependency_check_callback is not None:
            return self._dependency_check_callback(name)
        # 无回调时，无 manifest 的 skill 默认依赖满足
        if name not in self._manifests:
            return {"satisfied": True, "missing": [], "warnings": []}
        return {
            "satisfied": False,
            "missing": [],
            "warnings": ["依赖检查器未注入，无法确认依赖状态"],
        }

    def ensure_dependencies(self, name: str) -> Dict:
        """
        检查并按需安装 skill 依赖（首次加载触发点）

        Returns:
            {
                "installed": bool,            # 是否触发了安装
                "satisfied": bool,            # 最终是否满足
                "packages_installed": List[str],
                "error": str,
            }
        """
        if self._dependency_install_callback is None:
            # 未注入安装回调（开发环境/测试），视为满足
            return {
                "installed": False,
                "satisfied": True,
                "packages_installed": [],
                "error": "",
            }
        return self._dependency_install_callback(name)

    def reload(self) -> List[Dict]:
        """重新扫描目录 + 清缓存（供 API 调用）"""
        self._content_cache.clear()
        self._manifests.clear()
        return self.discover_skills()

    @property
    def skills_dir(self) -> str:
        """获取用户本地技能目录路径"""
        return self._user_skills_dir

    @property
    def total_count(self) -> int:
        """获取已发现技能总数（含禁用的）"""
        return len(self._skills)
