"""
Skill 文件加载器

负责从多个目录加载 Skill 定义文件（SKILL.md）。
支持两种目录结构：
- 子目录模式：{skills_dir}/{skill_name}/SKILL.md（优先）
- 扁平模式：{skills_dir}/{skill_name}.md（备选）

frontmatter 使用 yaml.safe_load 解析（取代旧版正则），支持完整 YAML 语法。
"""
import logging
import re
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

# frontmatter 分隔符正则：仅用于切分 YAML 块与正文，块内解析交给 yaml.safe_load
_FRONTMATTER_PATTERN = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n",
    re.DOTALL,
)

# 用户本地 skill 目录：项目根目录/config/skills
_DEFAULT_USER_SKILLS_DIR = str(
    Path(__file__).parent.parent.parent.parent.parent / "config" / "skills"
)

# 内置示例 skill 目录：随代码发布
_BUILTIN_SKILLS_DIR = str(Path(__file__).parent / "builtin")

# Git/registry 安装的临时缓存目录（.gitignore）
_CACHE_SKILLS_SUBDIR = ".cache"


def parse_skill_metadata(file_path: str) -> dict:
    """
    解析 SKILL.md 的 YAML frontmatter 元数据

    使用 yaml.safe_load 解析 frontmatter 块，支持完整 YAML 语法
    （列表、嵌套、多行、引号转义等）。

    Args:
        file_path: SKILL.md 文件的路径

    Returns:
        包含元数据的字典，解析失败时返回仅含 file_path 的字典。
        兼容官方 Agent Skills 规范的字段：name/description/license/compatibility/
        metadata/allowed-tools，并保留旧版 version/user-invocable 字段。
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

    try:
        parsed = yaml.safe_load(yaml_block)
    except yaml.YAMLError as e:
        logger.error(f"Skill frontmatter YAML 解析失败 {file_path}: {e}")
        return {"file_path": file_path}

    if not isinstance(parsed, dict):
        logger.warning(f"Skill frontmatter 必须是字典 {file_path}")
        return {"file_path": file_path}

    metadata: dict = {
        "file_path": str(file_path),
        "name": None,
        "description": "",
        "version": "0.0.0",
        "user_invocable": True,
        "license": None,
        "compatibility": None,
        "metadata": {},
        "allowed_tools": [],
    }

    # 兼容官方规范字段名（kebab-case）与 Python 字段名（snake_case）
    if "name" in parsed:
        metadata["name"] = str(parsed["name"]).strip()
    if "description" in parsed:
        metadata["description"] = str(parsed["description"]).strip()
    if "version" in parsed:
        metadata["version"] = str(parsed["version"]).strip()
    if "user-invocable" in parsed:
        metadata["user_invocable"] = bool(parsed["user-invocable"])
    elif "user_invocable" in parsed:
        metadata["user_invocable"] = bool(parsed["user_invocable"])
    if "license" in parsed:
        metadata["license"] = str(parsed["license"]).strip()
    if "compatibility" in parsed:
        metadata["compatibility"] = str(parsed["compatibility"]).strip()
    if "metadata" in parsed and isinstance(parsed["metadata"], dict):
        metadata["metadata"] = parsed["metadata"]
    if "allowed-tools" in parsed:
        at = parsed["allowed-tools"]
        if isinstance(at, str):
            metadata["allowed_tools"] = at.split()
        elif isinstance(at, list):
            metadata["allowed_tools"] = [str(x) for x in at]

    # 若 frontmatter 未指定 name，从文件名/目录名推断
    if metadata["name"] is None:
        metadata["name"] = (
            path.parent.name if path.name == "SKILL.md" else path.stem
        )

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

    # 优先：子目录模式 {skills_dir}/{skill_name}/SKILL.md
    subdir_path = base / skill_name / "SKILL.md"
    if subdir_path.exists():
        return str(subdir_path.resolve())

    # 备选：扁平模式 {skills_dir}/{skill_name}.md
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
        skills_dir: 技能根目录，默认使用用户本地目录 config/skills/

    Returns:
        SKILL.md 的完整文本内容，未找到时返回 None
    """
    if skills_dir is None:
        skills_dir = _DEFAULT_USER_SKILLS_DIR

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


def get_default_user_skills_dir() -> str:
    """获取用户本地 skill 目录（config/skills）"""
    return _DEFAULT_USER_SKILLS_DIR


def get_builtin_skills_dir() -> str:
    """获取内置示例 skill 目录（随代码发布）"""
    return _BUILTIN_SKILLS_DIR


def get_cache_skills_dir() -> str:
    """获取 Git/registry 安装的缓存目录（config/skills/.cache）"""
    return str(Path(_DEFAULT_USER_SKILLS_DIR) / _CACHE_SKILLS_SUBDIR)


def get_skill_dirs() -> list:
    """
    获取所有 skill 根目录列表（按优先级从高到低）：
    1. 用户本地 config/skills/
    2. Git/registry 缓存 config/skills/.cache/
    3. 内置示例 app/engine/tools/skill/builtin/

    Returns:
        目录路径列表（字符串形式）
    """
    return [
        _DEFAULT_USER_SKILLS_DIR,
        get_cache_skills_dir(),
        _BUILTIN_SKILLS_DIR,
    ]
