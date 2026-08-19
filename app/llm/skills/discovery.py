"""
Skill 发现（参考 claude-code loadSkillsDir + Agent Skills 规范）

- 目录式：{skill-name}/SKILL.md，skill 名取目录名
- frontmatter（yaml）必填 description；可选 when_to_use / disable-model-invocation
- 扫描目录优先级从高到低，同名目录先到先得（不覆盖）
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from app.utils.logging_init import get_logger

logger = get_logger("app.llm.skills")

DEFAULT_SKILL_DIRS = ["config/skills"]  # 相对项目根


@dataclass
class SkillMeta:
    """渐进式披露第一阶段：只有 name + description 进入上下文"""

    name: str
    description: str
    when_to_use: str = ""
    disable_model_invocation: bool = False
    skill_dir: str = ""
    frontmatter: Dict = field(default_factory=dict)


def parse_skill_md(path: Path) -> Optional[SkillMeta]:
    """解析单个 SKILL.md：frontmatter 校验，返回元数据；不合规返回 None"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning(f"⚠️ [skills] 读取失败 {path}: {e}")
        return None

    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not fm_match:
        logger.warning(f"⚠️ [skills] 缺少 frontmatter: {path}")
        return None
    try:
        fm = yaml.safe_load(fm_match.group(1)) or {}
    except yaml.YAMLError as e:
        logger.warning(f"⚠️ [skills] frontmatter 解析失败 {path}: {e}")
        return None

    description = str(fm.get("description", "")).strip()
    if not description:
        logger.warning(f"⚠️ [skills] frontmatter 缺少 description，跳过: {path}")
        return None

    return SkillMeta(
        name=path.parent.name,
        description=description,
        when_to_use=str(fm.get("when_to_use", "") or fm.get("whenToUse", "")).strip(),
        disable_model_invocation=bool(fm.get("disable-model-invocation", False)),
        skill_dir=str(path.parent.resolve()),
        frontmatter=fm,
    )


def discover_skills(skill_dirs: Optional[List[str]] = None) -> Dict[str, SkillMeta]:
    """扫描各目录的 {name}/SKILL.md。同名先到先得（靠前目录优先）。"""
    from app.llm.config import project_root

    roots: List[Path] = []
    if skill_dirs:
        roots = [Path(d) for d in skill_dirs]
    else:
        root = project_root()
        roots = [root / d for d in DEFAULT_SKILL_DIRS]

    found: Dict[str, SkillMeta] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for skill_md in sorted(root.glob("*/SKILL.md")):
            meta = parse_skill_md(skill_md)
            if meta is None:
                continue
            if meta.name.startswith("."):
                continue  # 跳过 .cache 等隐藏目录
            if meta.name in found:
                logger.debug(f"[skills] 跳过重复 skill: {meta.name}")
                continue
            found[meta.name] = meta
    logger.info(f"📦 [skills] 发现 {len(found)} 个 skill: {sorted(found)}")
    return found
