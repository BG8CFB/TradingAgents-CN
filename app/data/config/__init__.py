"""数据平台配置加载工具 — YAML 读取的统一入口（mtime 感知缓存）。

全部 app/data/config/ 下的 YAML 一律经 load_yaml 读取：文件变更自动重载
（热更），各处不再自建缓存或内联直读（治理组 3 收敛，2026-11-02）。
"""

import os
import threading
from typing import Any, Dict, Tuple

import yaml

_CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))

_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}  # filename -> (mtime, data)
_cache_lock = threading.Lock()


def load_yaml(filename: str) -> Dict[str, Any]:
    """加载 app/data/config/ 下的 YAML（mtime 变化自动重载；缺失返回 {}）。"""
    filepath = os.path.join(_CONFIG_DIR, filename)
    try:
        mtime = os.path.getmtime(filepath)
    except OSError:
        with _cache_lock:
            _cache.pop(filename, None)
        return {}
    with _cache_lock:
        cached = _cache.get(filename)
        if cached and cached[0] == mtime:
            return cached[1]
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        raise
    with _cache_lock:
        _cache[filename] = (mtime, data)
    return data


def cache_clear() -> None:
    """清空加载缓存（测试用）。"""
    with _cache_lock:
        _cache.clear()


def get_enabled_sources(market: str) -> list:
    """返回指定市场所有非 none 的数据源（去重）。"""
    matrix = load_yaml("capability_matrix.yaml")
    market_data = matrix.get(market, {})
    sources = set()
    for _domain, src_map in market_data.items():
        for src, level in src_map.items():
            if level and level != "none":
                sources.add(src)
    return sorted(sources)
