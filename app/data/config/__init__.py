"""数据平台配置加载工具。"""

import os
import functools
from typing import Any, Dict

import yaml


_CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))


@functools.lru_cache(maxsize=16)
def load_yaml(filename: str) -> Dict[str, Any]:
    """从 app/data/config/ 目录加载 YAML 配置文件。

    使用 lru_cache 缓存解析结果，避免重复文件I/O和YAML解析。
    如需强制刷新，调用 load_yaml.cache_clear()。
    """
    filepath = os.path.join(_CONFIG_DIR, filename)
    if not os.path.exists(filepath):
        return {}
    with open(filepath, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


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
