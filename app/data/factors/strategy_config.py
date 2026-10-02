"""strategies.yaml 加载 — 数据层（评分）与服务层（策略运行）共用的唯一事实源。

mtime 缓存：热重载环境下改 YAML 后无需重启进程。
"""

import logging
import os
from typing import Dict, List

import yaml

logger = logging.getLogger(__name__)

_CONFIG_NAME = "strategies.yaml"
_SEARCH_DIRS = [
    # 1) 环境变量显式覆盖（测试/自定义部署；_locate 内每次读取，运行期可覆盖）
    "env",
    # 2) 仓库内标准位置（容器内 /app/config/...，宿主机项目根）
    "config/screening/strategies.yaml",
    "/app/config/screening/strategies.yaml",
]

_cache: dict | None = None
_cache_mtime: float | None = None


def _locate() -> str:
    for path in _SEARCH_DIRS:
        if path == "env":
            path = os.environ.get("SCREENING_STRATEGIES_FILE") or ""
        if path and os.path.isfile(path):
            return path
    raise FileNotFoundError(f"未找到选股策略配置 {_CONFIG_NAME}")


def load_strategy_config() -> Dict:
    """读取并缓存 strategies.yaml（mtime 变化时自动重载）。"""
    global _cache, _cache_mtime
    path = _locate()
    mtime = os.path.getmtime(path)
    if _cache is not None and mtime == _cache_mtime:
        return _cache
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    _validate(cfg)
    _cache = cfg
    _cache_mtime = mtime
    logger.info("已加载选股策略配置 %s（%d 个模板）", path, len(cfg.get("strategies", [])))
    return cfg


def _validate(cfg: Dict) -> None:
    """配置合法性校验：权重和、组引用、id 唯一、默认模板唯一、条件字段在因子清单内。"""
    weights = cfg.get("score_weights") or {}
    groups = cfg.get("factor_groups") or {}
    strategies = cfg.get("strategies") or []
    if not weights or not groups or not strategies:
        raise ValueError("strategies.yaml 缺少 score_weights/factor_groups/strategies")
    for style, w in weights.items():
        if abs(sum(w.values()) - 1.0) > 1e-6:
            raise ValueError(f"风格 {style} 组权重和 != 1: {w}")
        unknown = set(w) - set(groups)
        if unknown:
            raise ValueError(f"风格 {style} 引用未知因子组: {unknown}")
    known_factors = {f for fs in groups.values() for f in fs}
    ids = [s.get("id") for s in strategies]
    if len(set(ids)) != len(ids) or None in ids:
        raise ValueError(f"策略 id 重复或缺失: {ids}")
    if sum(1 for s in strategies if s.get("default")) != 1:
        raise ValueError("必须恰好一个 default: true 的策略模板")
    for s in strategies:
        if s.get("style") not in weights:
            raise ValueError(f"策略 {s['id']} 引用未知风格 {s.get('style')}")
        for cond in s.get("filters", []):
            if cond.get("field") not in known_factors:
                raise ValueError(f"策略 {s['id']} 条件字段 {cond.get('field')} 不在因子清单")


def get_factor_groups() -> Dict[str, List[str]]:
    return load_strategy_config()["factor_groups"]


def get_style_weights() -> Dict[str, Dict[str, float]]:
    return load_strategy_config()["score_weights"]


def get_strategies() -> List[Dict]:
    return load_strategy_config()["strategies"]


def get_default_strategy() -> Dict:
    return next(s for s in get_strategies() if s.get("default"))
