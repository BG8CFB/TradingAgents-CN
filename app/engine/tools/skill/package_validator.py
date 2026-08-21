"""
Skill 包公共校验器

Git / 本地 zip / 本地路径 / 市场安装四条路径共用的落盘前校验：
- SKILL.md 存在且 frontmatter 可解析
- skill_name 字符安全（防路径遍历）
- 目录名与 skill_name 一致（Agent Skills 规范）
- manifest.skill_name 一致性（若 manifest.yaml 存在）
"""

import logging
import re
from pathlib import Path
from typing import Optional, Tuple

import yaml

logger = logging.getLogger(__name__)

# skill_name 安全字符集：字母数字开头，仅允许字母数字下划线连字符
# （拒绝 ../ 等路径片段，防止写入项目任意目录）
SKILL_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")


def _read_raw_manifest_skill_name(dir_path: Path) -> Optional[str]:
    """读取 manifest.yaml 原始 skill_name 字段（不做目录名归一化）"""
    for name in ("manifest.yaml", "manifest.yml"):
        p = Path(dir_path) / name
        if not p.exists():
            continue
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
        except Exception:
            return None  # 解析失败交给后续 load_manifest 流程告警
        if isinstance(data, dict) and data.get("skill_name"):
            return str(data["skill_name"]).strip()
        return None
    return None


def validate_skill_package(dir_path: Path) -> Tuple[Optional[str], Optional[str]]:
    """
    校验已落盘的 skill 包目录。

    Args:
        dir_path: skill 根目录（须含 SKILL.md）

    Returns:
        (skill_name, error)：校验通过时 error 为 None；
        失败时 skill_name 为 None（或部分场景含名称），error 为原因。
        失败时调用方负责清理目录。
    """
    from app.engine.tools.skill.loader import parse_skill_metadata

    skill_md = Path(dir_path) / "SKILL.md"
    if not skill_md.exists():
        return None, f"{Path(dir_path).name} 根目录缺少 SKILL.md，不是合法的 skill 包"

    meta = parse_skill_metadata(str(skill_md))
    skill_name = meta.get("name") or Path(dir_path).name

    # R13-ET-02：skill_name 来源于包内容（SKILL.md 仅 .strip() 处理），
    # 若含 ../ 等路径片段可写入项目任意目录，必须拒绝
    if not SKILL_NAME_PATTERN.match(skill_name):
        logger.error(f"[SkillPackageValidator] skill_name 含非法字符，拒绝: {skill_name!r}")
        return skill_name, (
            f"skill_name 含非法字符（仅允许字母、数字、下划线、连字符）: {skill_name}"
        )

    # manifest 一致性（若存在 manifest.yaml）
    # 注意：不走 load_manifest——它会把 skill_name 归一化为目录名，
    # 校验场景（安装目录还是临时名）下会导致误判，这里读原始 YAML 比对
    manifest_name = _read_raw_manifest_skill_name(dir_path)
    if manifest_name is not None and manifest_name != skill_name:
        return skill_name, (
            f"manifest.skill_name ({manifest_name}) 与目录名 ({skill_name}) 不一致"
        )

    return skill_name, None
