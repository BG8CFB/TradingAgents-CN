#!/usr/bin/env python3
"""
TradingAgents 运行时配置适配器（弱依赖）

- 优先尝试从后端 app.services.config_provider 读取动态 system_settings（若可用）
- 若不可用或在异步事件循环中无法同步等待，则回退到环境变量与默认值
- 保持 TradingAgents 包独立性：不可用时静默回退，不引入硬依赖
"""

from __future__ import annotations

import os
import asyncio
import threading
from typing import Any, Optional, Callable

import logging
_logger = logging.getLogger("tradingagents.config")

# 模块级缓存：启动时从 async 上下文注入，运行时从 sync 上下文读取
_cached_settings: dict = {}
_cache_lock = threading.Lock()


def set_cached_settings(settings: dict) -> None:
    """从 async 上下文（如 FastAPI lifespan）注入动态配置缓存。
    只需在启动阶段调用一次即可。
    """
    global _cached_settings
    with _cache_lock:
        _cached_settings = dict(settings) if settings else {}
    _logger.info(f"[runtime_settings] 动态配置缓存已更新，共 {len(_cached_settings)} 项")


def _get_system_settings_sync() -> dict:
    """获取后端动态 system_settings。
    配置在启动时通过 set_cached_settings() 注入缓存，此函数从缓存读取。
    若缓存为空（启动前或未调用注入），则回退到环境变量和默认值。
    """
    if _cached_settings:
        return _cached_settings
    _logger.debug("动态配置缓存为空，使用环境变量和默认值")
    return {}


def _coerce(value: Any, caster: Callable[[Any], Any], default: Any) -> Any:
    try:
        if value is None:
            return default
        return caster(value)
    except Exception:
        return default


def get_number(env_var: str, system_key: Optional[str], default: float | int, caster: Callable[[Any], Any]) -> float | int:
    """按优先级获取数值配置：DB(system_settings) > ENV > default
    - env_var: 环境变量名，例如 "TA_US_MIN_API_INTERVAL_SECONDS"
    - system_key: 动态系统设置键名，例如 "ta_us_min_api_interval_seconds"（可为 None）
    - default: 默认值
    - caster: 类型转换函数，如 float 或 int
    """
    # 1) DB 动态设置
    if system_key:
        eff = _get_system_settings_sync()
        if isinstance(eff, dict) and system_key in eff:
            return _coerce(eff.get(system_key), caster, default)

    # 2) 环境变量
    env_val = os.getenv(env_var)
    if env_val is not None and str(env_val).strip() != "":
        return _coerce(env_val, caster, default)

    # 3) 代码默认
    return default


def get_float(env_var: str, system_key: Optional[str], default: float) -> float:
    return get_number(env_var, system_key, default, float)  # type: ignore[arg-type]


def get_int(env_var: str, system_key: Optional[str], default: int) -> int:
    return get_number(env_var, system_key, default, int)  # type: ignore[arg-type]


# --- Boolean access helper ---------------------------------------------------

def get_bool(env_var: str, system_key: Optional[str], default: bool) -> bool:
    """按优先级获取布尔配置：DB(system_settings) > ENV > default"""
    # 1) DB 动态设置
    if system_key:
        eff = _get_system_settings_sync()
        if isinstance(eff, dict) and system_key in eff:
            v = eff.get(system_key)
            if isinstance(v, bool):
                return v
            if isinstance(v, (int, float)):
                return bool(v)
            if isinstance(v, str):
                return str(v).strip().lower() in ("1", "true", "yes", "on")
    # 2) 环境变量
    env_val = os.getenv(env_var)
    if env_val is not None and str(env_val).strip() != "":
        return str(env_val).strip().lower() in ("1", "true", "yes", "on")
    # 3) 代码默认
    return default


def use_app_cache_enabled(default: bool = False) -> bool:
    """是否启用从 app 缓存（Mongo 集合）优先读取。ENV: TA_USE_APP_CACHE; DB: ta_use_app_cache
    会记录一次评估日志，包含来源与原始ENV值，便于排查生效路径。
    """
    # 推断来源（DB/ENV/DEFAULT）
    src = "default"
    env_val = os.getenv("TA_USE_APP_CACHE")
    try:
        eff = _get_system_settings_sync()
    except Exception:
        eff = {}
    if isinstance(eff, dict) and "ta_use_app_cache" in eff:
        src = "db"
    elif env_val is not None and str(env_val).strip() != "":
        src = "env"

    # 最终值（遵循 DB > ENV > DEFAULT）
    val = get_bool("TA_USE_APP_CACHE", "ta_use_app_cache", default)

    try:
        _logger.info(f"[runtime_settings] TA_USE_APP_CACHE evaluated -> {val} (source={src}, env={env_val})")
    except Exception:
        pass
    return val


# --- Timezone access helpers -------------------------------------------------
from typing import Optional as _Optional
from zoneinfo import ZoneInfo as _ZoneInfo


def get_timezone_name(default: str = "Asia/Shanghai") -> str:
    """Return configured timezone name with priority: DB(system_settings) > ENV > default.
    - DB key: app_timezone (preferred) or APP_TIMEZONE
    - ENV vars checked in order: APP_TIMEZONE, TIMEZONE, TA_TIMEZONE
    """
    try:
        eff = _get_system_settings_sync()
        if isinstance(eff, dict):
            tz = eff.get("app_timezone") or eff.get("APP_TIMEZONE")
            if isinstance(tz, str) and tz.strip():
                return tz.strip()
    except Exception:
        pass

    for env_key in ("APP_TIMEZONE", "TIMEZONE", "TA_TIMEZONE"):
        val = os.getenv(env_key)
        if isinstance(val, str) and val.strip():
            return val.strip()

    return default


def get_zoneinfo(default: str = "Asia/Shanghai") -> _ZoneInfo:
    """Convenience: return ZoneInfo for the configured timezone name."""
    name = get_timezone_name(default)
    try:
        return _ZoneInfo(name)
    except Exception:
        # Fallback to UTC if invalid
        return _ZoneInfo("UTC")


__all__ = [
    "get_float",
    "get_int",
    "get_bool",
    "use_app_cache_enabled",
    "get_timezone_name",
    "get_zoneinfo",
    "set_cached_settings",
]
