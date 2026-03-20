"""
Skill 注册表

管理技能的发现、加载和启用/禁用状态。
扫描 config/skills/ 目录，支持子目录和扁平两种结构。
"""
import logging
from pathlib import Path
from typing import Dict, List, Optional

from .loader import parse_skill_metadata, load_skill_content, _DEFAULT_SKILLS_DIR

logger = logging.getLogger(__name__)


class SkillRegistry:
    """
    技能注册表

    负责扫描技能目录、管理技能元数据和控制启用状态。
    """

    def __init__(self, skills_dir: Optional[str] = None):
        """
        初始化技能注册表

        Args:
            skills_dir: 技能根目录路径，默认使用 config/skills/
        """
        self._skills_dir = skills_dir or _DEFAULT_SKILLS_DIR
        self._skills: List[Dict] = []           # 所有已发现的技能元数据
        self._disabled: set = set()             # 已禁用的技能名称集合
        self._content_cache: Dict[str, str] = {} # 技能内容缓存

        # 启动时自动发现
        self.discover_skills()

    def discover_skills(self) -> List[Dict]:
        """
        扫描技能目录，发现所有已安装的 Skill

        支持两种目录结构（子目录优先）：
        - config/skills/{skill_name}/SKILL.md
        - config/skills/{skill_name}.md

        Returns:
            技能元数据列表，每项包含：
            - name: 技能名称
            - description: 技能描述
            - version: 版本号
            - user_invocable: 是否允许用户调用
            - path: 文件路径
        """
        base = Path(self._skills_dir)
        if not base.exists():
            logger.info(f"技能目录不存在，跳过发现: {base.resolve()}")
            self._skills = []
            return self._skills

        discovered = []
        seen_names = set()

        # 1. 扫描子目录模式：config/skills/{name}/SKILL.md
        for subdir in sorted(base.iterdir()):
            if not subdir.is_dir():
                continue
            skill_md = subdir / "SKILL.md"
            if not skill_md.exists():
                continue

            meta = parse_skill_metadata(str(skill_md))
            name = meta.get("name")
            if not name or name in seen_names:
                continue

            seen_names.add(name)
            discovered.append({
                "name": name,
                "description": meta.get("description", ""),
                "version": meta.get("version", "0.0.0"),
                "user_invocable": meta.get("user_invocable", True),
                "path": str(skill_md.resolve()),
            })

        # 2. 扫描扁平模式：config/skills/{name}.md
        for md_file in sorted(base.glob("*.md")):
            # 跳过非技能文件（如 .gitkeep 不是 .md 但以防万一）
            if md_file.name.upper() == "SKILL.MD":
                continue
            if not md_file.is_file():
                continue

            meta = parse_skill_metadata(str(md_file))
            name = meta.get("name")
            if not name or name in seen_names:
                continue

            seen_names.add(name)
            discovered.append({
                "name": name,
                "description": meta.get("description", ""),
                "version": meta.get("version", "0.0.0"),
                "user_invocable": meta.get("user_invocable", True),
                "path": str(md_file.resolve()),
            })

        self._skills = discovered
        # 清除内容缓存（目录内容可能已变化）
        self._content_cache.clear()

        logger.info(f"技能发现完成: 共发现 {len(discovered)} 个技能")
        return self._skills

    def get_skill_content(self, name: str) -> Optional[str]:
        """
        获取指定技能的 SKILL.md 完整内容

        带缓存机制，避免重复读取文件。

        Args:
            name: 技能名称

        Returns:
            SKILL.md 的完整文本，未找到或已禁用时返回 None
        """
        if not self.is_enabled(name):
            logger.warning(f"技能已禁用: {name}")
            return None

        # 命中缓存
        if name in self._content_cache:
            return self._content_cache[name]

        content = load_skill_content(name, self._skills_dir)
        if content is not None:
            self._content_cache[name] = content

        return content

    def list_skills(self) -> List[Dict]:
        """
        列出所有已启用且用户可调用的技能

        用于生成 load_skill 工具的 description。

        Returns:
            技能摘要列表，每项包含 name 和 description
        """
        return [
            {"name": s["name"], "description": s["description"]}
            for s in self._skills
            if s.get("user_invocable", True) and s["name"] not in self._disabled
        ]

    def enable_skill(self, name: str) -> bool:
        """
        启用指定技能

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
        # 清除缓存以重新加载
        self._content_cache.pop(name, None)
        logger.info(f"技能已启用: {name}")
        return True

    def disable_skill(self, name: str) -> bool:
        """
        禁用指定技能

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

    def is_enabled(self, name: str) -> bool:
        """
        检查指定技能是否启用

        Args:
            name: 技能名称

        Returns:
            技能是否存在且已启用
        """
        skill_names = {s["name"] for s in self._skills}
        return name in skill_names and name not in self._disabled

    @property
    def skills_dir(self) -> str:
        """获取当前技能目录路径"""
        return self._skills_dir

    @property
    def total_count(self) -> int:
        """获取已发现技能总数（含禁用的）"""
        return len(self._skills)
