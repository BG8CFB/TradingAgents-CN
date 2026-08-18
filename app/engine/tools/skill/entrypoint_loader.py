"""
Skill 脚本入口加载器

把 skill manifest 中声明的 entrypoints 注册为 builtin 工具，
让 LLM 通过 ToolRegistry 像调用普通工具一样调用 skill 脚本。

实现要点：
- 将每个 skill 的根目录加入 sys.path（仅一次），让 scripts.entry 这样的模块路径可导入
- 通过 BuiltinToolSpec.register_skill_entrypoint 追加到 BUILTIN_TOOL_REGISTRY
- tool_id 约定为 {skill_name}.{entrypoint_name}（kebab-case）
- 使用 _lazy_import 避免循环依赖，与现有 builtin 工具一致
- 依赖未满足的入口不注册（避免运行时崩溃）
"""
import importlib
import logging
import os
import sys
from typing import Dict, List

from app.engine.tools.builtin.registry import (
    BuiltinToolSpec,
    register_skill_entrypoint,
    unregister_skill_entrypoints,
)
from app.engine.tools.skill.availability import check_skill_dependencies
from app.engine.tools.skill.registry import SkillRegistry

logger = logging.getLogger(__name__)

# 标准库/危险模块黑名单：skill 入口不得导入这些模块
# 仅禁可直接执行系统命令/进程/FFI 的模块；asyncio 不在列（合法异步 skill 需用，
# 且其 subprocess 子能力由 subprocess 黑名单 + skill_dir 路径校验间接约束）
_FORBIDDEN_MODULES = frozenset({
    "os", "sys", "subprocess", "shutil", "builtins",
    "importlib", "ctypes", "multiprocessing",
})


def _validate_module_path(module: str, skill_dir: str) -> None:
    """
    校验待导入的 module 安全：
    1. 不在标准库/危险模块黑名单内（顶层名称）
    2. import_module 解析后的文件路径必须在 skill_dir 内部（防 .. 穿越）
    """
    top_level = module.split(".")[0]
    if top_level in _FORBIDDEN_MODULES:
        raise ValueError(f"禁止导入模块: {module}（顶层 {top_level} 在黑名单中）")

    # 解析实际文件路径
    try:
        spec = importlib.util.find_spec(module)
    except (ModuleNotFoundError, ValueError, ImportError):
        # 模块尚未可解析（可能在 skill_dir 加入 sys.path 后才能找到）
        # 这种情况下路径校验延迟到真正 import 时，但黑名单已拦截
        return

    if spec is not None and spec.origin:
        real_origin = os.path.realpath(spec.origin)
        real_skill_dir = os.path.realpath(skill_dir)
        if not real_origin.startswith(real_skill_dir + os.sep):
            raise ValueError(
                f"模块 {module} 文件路径 {real_origin} 不在 skill 目录 {real_skill_dir} 内"
            )


def _ensure_skill_on_path(skill_dir: str) -> None:
    """把 skill 根目录加入 sys.path（幂等）"""
    if not skill_dir:
        return
    if skill_dir not in sys.path:
        sys.path.insert(0, skill_dir)


def _make_lazy_entry(skill_dir: str, module: str, function: str):
    """
    构造 lazy 入口函数（与 builtin/registry.py 的 _lazy_import 一致）。

    延迟到首次调用时导入模块与函数，避免 skill 发现阶段就触发导入错误。
    """
    _real_fn = None

    def wrapper(*args, **kwargs):
        nonlocal _real_fn
        if _real_fn is None:
            _ensure_skill_on_path(skill_dir)
            _validate_module_path(module, skill_dir)
            mod = importlib.import_module(module)
            _real_fn = getattr(mod, function)
        return _real_fn(*args, **kwargs)

    wrapper.__name__ = function
    wrapper.__qualname__ = function
    wrapper.__doc__ = ""
    wrapper._lazy_module = module
    wrapper._lazy_func_name = function
    wrapper._skill_dir = skill_dir
    return wrapper


def load_all_skill_entrypoints() -> Dict[str, List[str]]:
    """
    遍历所有已发现的 skill，把入口注册为 builtin 工具。

    流程：
    1. 从 SkillRegistry 拿到全部 skill
    2. 对每个有 manifest 的 skill：
       a. 检查依赖（不触发自动安装，自动安装在 ensure_dependencies 阶段已完成）
       b. 依赖满足 → 把 skill_dir 加入 sys.path
       c. 遍历 entrypoints，构造 BuiltinToolSpec 并注册
    3. 依赖未满足 → 跳过，记录到 unavailable 列表

    Returns:
        {
            "registered": {skill_name: [entrypoint_names]},
            "unavailable": {skill_name: [reason]},
        }
    """
    registry = SkillRegistry.get_instance()
    all_skills = registry.list_all_skills()

    registered: Dict[str, List[str]] = {}
    unavailable: Dict[str, List[str]] = {}

    for skill_meta in all_skills:
        name = skill_meta["name"]
        if not skill_meta.get("has_manifest"):
            continue

        manifest = registry.get_manifest(name)
        if manifest is None or not manifest.entrypoints:
            continue

        # 依赖检查（ensure_dependencies 已在 ToolRegistry.initialize 前完成）
        availability = check_skill_dependencies(name)
        if not (availability.dependencies_satisfied and availability.env_satisfied):
            reason = (
                f"依赖未满足: 缺失 {[d.package for d in availability.dependencies if not d.satisfied]}"
                if not availability.dependencies_satisfied
                else f"环境变量缺失: {availability.missing_env}"
            )
            unavailable[name] = [reason]
            logger.info(f"[SkillEntry] 跳过 {name}（{reason}）")
            continue

        skill_dir = registry.get_skill_dir(name)
        if not skill_dir:
            unavailable[name] = ["skill_dir 不存在"]
            continue

        # 确保 skill 根目录在 sys.path
        _ensure_skill_on_path(skill_dir)

        registered_names: List[str] = []
        for ep in manifest.entrypoints:
            tool_id = f"{name}.{ep.name}"
            try:
                fn = _make_lazy_entry(skill_dir, ep.module, ep.function)
                spec = BuiltinToolSpec(
                    tool_id=tool_id,
                    display_name=ep.display_name,
                    domains=ep.domains,
                    markets=[m.upper() for m in ep.markets],
                    fn=fn,
                    inject_args=ep.inject_args,
                    description=ep.description,
                    non_standard=True,  # skill 工具标记为非标准
                )
                if register_skill_entrypoint(spec):
                    registered_names.append(ep.name)
            except Exception as e:
                logger.error(f"[SkillEntry] 注册 {tool_id} 失败: {e}")
                unavailable.setdefault(name, []).append(f"{ep.name}: {e}")

        if registered_names:
            registered[name] = registered_names

    total = sum(len(v) for v in registered.values())
    logger.info(
        f"[SkillEntry] 入口注册完成: {total} 个入口，"
        f"覆盖 {len(registered)} 个 skill；"
        f"{len(unavailable)} 个 skill 不可用"
    )
    return {"registered": registered, "unavailable": unavailable}


def unload_skill_entrypoints(skill_name: str) -> int:
    """卸载指定 skill 的全部入口（reload/delete 时调用）"""
    return unregister_skill_entrypoints(skill_name)
