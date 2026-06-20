"""
Skill 依赖可用性检查

对标 builtin/domain_checker，但针对 skill 的依赖类型：
- Python 包：importlib.util.find_spec
- 环境变量：os.environ.get

不执行安装（安装由 dependency_installer 负责）。
"""
import importlib.util
import logging
import os
from typing import Dict, List

from app.engine.tools.skill.registry import SkillRegistry
from app.models.skill import (
    SkillAvailability,
    SkillDependencyStatus,
    SkillManifest,
)

logger = logging.getLogger(__name__)


# Python importlib 通过 module name 查找；
# 一些包名与 module 名不同，此处维护映射
_PACKAGE_TO_MODULE = {
    "ta-lib": "talib",
    "ta_lib": "talib",
    "Pillow": "PIL",
    "pillow": "PIL",
    "pyyaml": "yaml",
    "mplfinance": "mplfinance",
    "pymupdf": "fitz",
    "beautifulsoup4": "bs4",
    "python-dateutil": "dateutil",
    "python-dotenv": "dotenv",
    "scikit-learn": "sklearn",
    "opencv-python": "cv2",
    "protobuf": "google.protobuf",
}


def _package_to_module(package_name: str) -> str:
    """把 PyPI 包名映射到 importlib 能识别的 module 名"""
    return _PACKAGE_TO_MODULE.get(package_name, package_name.replace("-", "_"))


def check_python_package(package: str) -> tuple:
    """
    检查 Python 包是否已安装。

    Args:
        package: PyPI 包名（如 ta-lib, mplfinance）

    Returns:
        (satisfied: bool, installed_version: str)
    """
    module_name = _package_to_module(package)
    try:
        spec = importlib.util.find_spec(module_name)
        if spec is None:
            return (False, "")
        # 尝试读取 __version__
        try:
            mod = importlib.import_module(module_name)
            version = getattr(mod, "__version__", "") or getattr(
                mod, "VERSION", ""
            )
            return (True, str(version))
        except Exception:
            # 能找到 spec 但 import 失败（如 ta-lib 缺 C 库），视为未满足
            return (False, "")
    except Exception as e:
        logger.debug(f"检查包 {package} (module={module_name}) 失败: {e}")
        return (False, "")


def check_env_var(name: str) -> bool:
    """检查环境变量是否已设置"""
    return bool(os.environ.get(name))


def check_skill_dependencies(name: str) -> SkillAvailability:
    """
    检查指定 skill 的全部依赖（Python 包 + 环境变量）是否满足。

    Args:
        name: skill 名

    Returns:
        SkillAvailability 对象
    """
    registry = SkillRegistry.get_instance()
    manifest: SkillManifest | None = registry.get_manifest(name)

    enabled = registry.is_enabled(name)
    warnings: List[str] = []

    # 无 manifest 的 skill 视为依赖满足（纯 prompt skill）
    if manifest is None:
        return SkillAvailability(
            skill_name=name,
            enabled=enabled,
            dependencies_satisfied=True,
            dependencies=[],
            env_satisfied=True,
            missing_env=[],
            entrypoints_available=[],
            entrypoints_unavailable=[],
            warnings=["无 manifest，视为纯 prompt skill"],
        )

    # 检查 Python 依赖
    dep_statuses: List[SkillDependencyStatus] = []
    all_satisfied = True
    missing_count = 0
    for dep in manifest.python_dependencies:
        satisfied, version = check_python_package(dep.package)
        if not satisfied:
            all_satisfied = False
            missing_count += 1
        dep_statuses.append(
            SkillDependencyStatus(
                package=dep.package,
                version_constraint=dep.version,
                satisfied=satisfied,
                installed_version=version,
                note=dep.note,
            )
        )

    # 检查环境变量
    missing_env: List[str] = []
    for env_req in manifest.env:
        if env_req.required and not check_env_var(env_req.name):
            missing_env.append(env_req.name)

    env_satisfied = len(missing_env) == 0
    if not env_satisfied:
        warnings.append(f"缺失必需环境变量: {', '.join(missing_env)}")

    # 系统依赖：只能提示，无法检查
    for sys_dep in manifest.system_dependencies:
        desc = sys_dep.get("description", "") if isinstance(sys_dep, dict) else str(sys_dep)
        if desc:
            warnings.append(f"系统依赖（需手动确认）: {desc}")

    # 入口可用性：依赖满足 → 入口全部可用
    entrypoint_names = [ep.name for ep in manifest.entrypoints]
    if all_satisfied and env_satisfied:
        entrypoints_available = entrypoint_names
        entrypoints_unavailable = []
    else:
        entrypoints_available = []
        entrypoints_unavailable = entrypoint_names

    return SkillAvailability(
        skill_name=name,
        enabled=enabled,
        dependencies_satisfied=all_satisfied,
        dependencies=dep_statuses,
        env_satisfied=env_satisfied,
        missing_env=missing_env,
        entrypoints_available=entrypoints_available,
        entrypoints_unavailable=entrypoints_unavailable,
        warnings=warnings,
    )


def check_skill_dependencies_raw(name: str) -> Dict:
    """
    check_skill_dependencies 的字典版本（供 SkillRegistry.check_dependencies 回调用）。

    Returns:
        {
            "satisfied": bool,
            "missing": List[str],
            "warnings": List[str],
            "availability": SkillAvailability (dict),
        }
    """
    try:
        availability = check_skill_dependencies(name)
        missing = [
            d.package for d in availability.dependencies if not d.satisfied
        ]
        return {
            "satisfied": availability.dependencies_satisfied
            and availability.env_satisfied,
            "missing": missing + availability.missing_env,
            "warnings": availability.warnings,
            "availability": availability.model_dump(),
        }
    except Exception as e:
        logger.error(f"检查 skill 依赖失败 {name}: {e}")
        return {
            "satisfied": False,
            "missing": [],
            "warnings": [f"检查异常: {e}"],
            "availability": None,
        }
