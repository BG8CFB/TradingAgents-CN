"""
manifest.yaml 解析与校验

读取 skill 包内的 manifest.yaml，校验为 SkillManifest 模型。
manifest.yaml 是可选文件——纯 prompt skill 无需 manifest。
"""
import logging
from pathlib import Path
from typing import Optional

import yaml
from pydantic import ValidationError

from app.models.skill import SkillManifest

logger = logging.getLogger(__name__)


def load_manifest(skill_dir: str) -> Optional[SkillManifest]:
    """
    从 skill 目录读取 manifest.yaml 并解析为 SkillManifest。

    Args:
        skill_dir: skill 根目录路径

    Returns:
        SkillManifest 实例；目录无 manifest.yaml 时返回 None；
        解析失败时返回 None 并记录错误日志（不抛异常，避免阻塞 discovery）。
    """
    manifest_path = Path(skill_dir) / "manifest.yaml"
    if not manifest_path.exists():
        # 也接受 manifest.yml
        manifest_path = Path(skill_dir) / "manifest.yml"
        if not manifest_path.exists():
            return None

    try:
        raw = manifest_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"读取 manifest 失败 {manifest_path}: {e}")
        return None

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        logger.error(f"manifest YAML 解析失败 {manifest_path}: {e}")
        return None

    if not isinstance(data, dict):
        logger.error(f"manifest 顶层必须是字典 {manifest_path}")
        return None

    # 兼容 manifest 中 dependencies.python 写法 → 映射到 python_dependencies
    deps = data.get("dependencies") or {}
    if isinstance(deps, dict) and "python" in deps and "python_dependencies" not in data:
        data["python_dependencies"] = deps["python"]
    if isinstance(deps, dict) and "system" in deps and "system_dependencies" not in data:
        data["system_dependencies"] = deps["system"]

    try:
        manifest = SkillManifest.model_validate(data)
    except ValidationError as e:
        logger.error(f"manifest 校验失败 {manifest_path}: {e}")
        return None

    # 校验 skill_name 与目录名一致
    dir_name = Path(skill_dir).name
    if manifest.skill_name != dir_name:
        logger.warning(
            f"manifest.skill_name ({manifest.skill_name}) 与目录名 ({dir_name}) 不一致，"
            f"将以目录名为准"
        )
        manifest.skill_name = dir_name

    return manifest


def has_manifest(skill_dir: str) -> bool:
    """快速判断 skill 目录是否包含 manifest.yaml"""
    return (Path(skill_dir) / "manifest.yaml").exists() or (
        Path(skill_dir) / "manifest.yml"
    ).exists()
