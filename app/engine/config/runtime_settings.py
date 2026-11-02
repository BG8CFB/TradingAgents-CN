#!/usr/bin/env python3
"""
TradingAgents 运行时配置适配器（弱依赖）

- 优先尝试从后端 app.services.config_provider 读取动态 system_settings（若可用）
- 若不可用或在异步事件循环中无法同步等待，则回退到环境变量与默认值
- 保持 TradingAgents 包独立性：不可用时静默回退，不引入硬依赖

（历史 get_number/get_float/get_int/get_bool/use_app_cache_enabled 五个数值
辅助函数零调用方，随治理清偿删除，2026-11-02；其中 use_app_cache_enabled
计算后缺 return 恒返 None，属死代码里潜伏的缺陷，一并消除）
"""

from __future__ import annotations

import threading

from app.core.env import get_env

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


# --- Timezone access helpers -------------------------------------------------
from zoneinfo import ZoneInfo as _ZoneInfo  # noqa: E402 (intentional late import)


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
    except Exception as e:
        _logger.debug(f"获取系统时区设置失败: {e}")
    for env_key in ("APP_TIMEZONE", "TIMEZONE", "TA_TIMEZONE"):
        val = get_env(env_key)
        if isinstance(val, str) and val.strip():
            return val.strip()

    return default


def get_zoneinfo(default: str = "Asia/Shanghai") -> _ZoneInfo:
    """Convenience: return ZoneInfo for the configured timezone name."""
    name = get_timezone_name(default)
    try:
        return _ZoneInfo(name)
    except Exception as e:
        _logger.debug(f"时区 '{name}' 无效，回退到 UTC: {e}")
        # Fallback to UTC if invalid
        return _ZoneInfo("UTC")


__all__ = [
    "get_timezone_name",
    "get_zoneinfo",
    "set_cached_settings",
]
