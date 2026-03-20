"""
Skill 文件加载器

负责从 config/skills/ 目录加载 Skill 定义文件（SKILL.md）。
支持两种目录结构：
- 子目录模式：config/skills/{skill_name}/SKILL.md（优先）
- 扁平模式：config/skills/{skill_name}.md（备选）

YAML frontmatter 使用正则解析，不依赖 PyYAML。
"""
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# YAML frontmatter 正则：匹配 --- 分隔的块
_FRONTMATTER_PATTERN = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n",
    re.DOTALL,
)

# 默认技能目录：基于本文件位置向上推导项目根目录，确保在任意工作目录下都能找到
# 文件位置：app/engine/tools/skill/loader.py → 上4级即项目根目录
_DEFAULT_SKILLS_DIR = str(Path(__file__).parent.parent.parent.parent.parent / "config" / "skills")


def parse_skill_metadata(file_path: str) -> dict:
    """
    解析 SKILL.md 的 YAML frontmatter 元数据

    使用正则匹配 ^---$ 分隔的 YAML 块，提取以下字段：
    - name: 技能名称
    - description: 技能描述
    - version: 版本号
    - user-invocable: 是否允许用户直接调用

    Args:
        file_path: SKILL.md 文件的路径

    Returns:
        包含元数据的字典，解析失败时返回仅含 file_path 的字典
    """
    path = Path(file_path)
    if not path.exists():
        logger.warning(f"Skill 文件不存在: {file_path}")
        return {"file_path": file_path}

    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"读取 Skill 文件失败 {file_path}: {e}")
        return {"file_path": file_path}

    match = _FRONTMATTER_PATTERN.match(content)
    if not match:
        logger.warning(f"Skill 文件缺少 YAML frontmatter: {file_path}")
        return {"file_path": file_path}

    yaml_block = match.group(1)
    metadata = {
        "file_path": str(file_path),
        "name": None,
        "description": "",
        "version": "0.0.0",
        "user_invocable": True,
    }

    # 逐行解析简单 YAML 键值对（仅支持简单标量值）
    for line in yaml_block.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        colon_idx = line.find(":")
        if colon_idx == -1:
            continue

        key = line[:colon_idx].strip().lower()
        value = line[colon_idx + 1:].strip()

        if key == "name" and value:
            metadata["name"] = value.strip('"').strip("'")
        elif key == "description" and value:
            metadata["description"] = value.strip('"').strip("'")
        elif key == "version" and value:
            metadata["version"] = value.strip('"').strip("'")
        elif key == "user-invocable":
            # 处理布尔值
            metadata["user_invocable"] = value.lower() in ("true", "yes", "1")

    # 如果 frontmatter 中未指定 name，从文件名推断
    if metadata["name"] is None:
        metadata["name"] = path.parent.name if path.name == "SKILL.md" else path.stem

    return metadata


def _resolve_skill_path(skills_dir: str, skill_name: str) -> Optional[str]:
    """
    解析技能文件路径（子目录优先，扁平备选）

    Args:
        skills_dir: 技能根目录
        skill_name: 技能名称

    Returns:
        SKILL.md 文件的绝对路径，未找到时返回 None
    """
    base = Path(skills_dir)

    # 优先：子目录模式 config/skills/{skill_name}/SKILL.md
    subdir_path = base / skill_name / "SKILL.md"
    if subdir_path.exists():
        return str(subdir_path.resolve())

    # 备选：扁平模式 config/skills/{skill_name}.md
    flat_path = base / f"{skill_name}.md"
    if flat_path.exists():
        return str(flat_path.resolve())

    return None


def load_skill_content(
    skill_name: str,
    skills_dir: Optional[str] = None,
) -> Optional[str]:
    """
    读取指定名称的 SKILL.md 完整内容

    Args:
        skill_name: 技能名称
        skills_dir: 技能根目录，默认使用 config/skills/

    Returns:
        SKILL.md 的完整文本内容，未找到时返回 None
    """
    if skills_dir is None:
        skills_dir = _DEFAULT_SKILLS_DIR

    file_path = _resolve_skill_path(skills_dir, skill_name)
    if file_path is None:
        logger.warning(f"未找到技能文件: {skill_name}（目录: {skills_dir}）")
        return None

    try:
        content = Path(file_path).read_text(encoding="utf-8")
        logger.debug(f"成功加载技能内容: {skill_name} ({file_path})")
        return content
    except Exception as e:
        logger.error(f"读取技能内容失败 {skill_name}: {e}")
        return None
