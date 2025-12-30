#!/usr/bin/env python3
"""
统一时间处理工具模块

最佳实践：
1. 内部存储使用 UTC（带时区信息）
2. 显示时转换为配置时区
3. 禁止使用 naive datetime
4. 禁止使用已弃用的 datetime.utcnow()

默认时区：Asia/Shanghai (UTC+8)
"""

from __future__ import annotations

import time as _time
from datetime import datetime, timezone, timedelta
from typing import Optional

from tradingagents.config.runtime_settings import get_timezone_name, get_zoneinfo


# ============================================================================
# 基础时间获取函数
# ============================================================================

def now_utc() -> datetime:
    """
    获取当前 UTC 时间（带时区信息）

    替代已弃用的 datetime.utcnow()

    Returns:
        datetime: 带 UTC 时区信息的当前时间
    """
    return datetime.now(timezone.utc)


def now_config_tz() -> datetime:
    """
    获取配置时区的当前时间

    Returns:
        datetime: 配置时区的当前时间（带时区信息）
    """
    return datetime.now(get_zoneinfo())


# ============================================================================
# 时区转换函数
# ============================================================================

def to_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """
    将 datetime 转换为 UTC 时区

    Args:
        dt: 要转换的 datetime，可为 None

    Returns:
        UTC 时区的 datetime，输入为 None 时返回 None
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        # naive datetime 假定为配置时区，然后转换为 UTC
        return dt.replace(tzinfo=get_zoneinfo()).astimezone(timezone.utc)
    return dt.astimezone(timezone.utc)


def to_config_tz(dt: Optional[datetime]) -> Optional[datetime]:
    """
    将 datetime 转换为配置时区

    Args:
        dt: 要转换的 datetime，可为 None

    Returns:
        配置时区的 datetime，输入为 None 时返回 None
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        # naive datetime 假定为 UTC，然后转换为配置时区
        return dt.replace(tzinfo=timezone.utc).astimezone(get_zoneinfo())
    return dt.astimezone(get_zoneinfo())


def ensure_tz(dt: Optional[datetime], default_to_utc: bool = False) -> Optional[datetime]:
    """
    确保 datetime 对象包含时区信息

    Args:
        dt: 要检查的 datetime
        default_to_utc: 如果为 True，naive datetime 默认为 UTC；否则默认为配置时区

    Returns:
        带时区信息的 datetime
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        if default_to_utc:
            return dt.replace(tzinfo=timezone.utc)
        return dt.replace(tzinfo=get_zoneinfo())
    return dt


# ============================================================================
# 时间格式化函数
# ============================================================================

def format_iso(dt: Optional[datetime]) -> Optional[str]:
    """
    格式化为 ISO 8601 格式（带时区信息）

    Args:
        dt: 要格式化的 datetime

    Returns:
        ISO 8601 格式字符串，如 "2024-01-01T20:00:00+08:00"
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = ensure_tz(dt)
    return dt.isoformat()


def format_date_short(dt: Optional[datetime]) -> Optional[str]:
    """
    格式化为短日期格式 YYYY-MM-DD

    Args:
        dt: 要格式化的 datetime

    Returns:
        短日期字符串，如 "2024-01-01"
    """
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%d")


def format_date_compact(dt: Optional[datetime]) -> Optional[str]:
    """
    格式化为紧凑日期格式 YYYYMMDD

    Args:
        dt: 要格式化的 datetime

    Returns:
        紧凑日期字符串，如 "20240101"
    """
    if dt is None:
        return None
    return dt.strftime("%Y%m%d")


def format_datetime(dt: Optional[datetime]) -> Optional[str]:
    """
    格式化为完整日期时间格式 YYYY-MM-DD HH:MM:SS

    Args:
        dt: 要格式化的 datetime

    Returns:
        完整日期时间字符串，如 "2024-01-01 20:00:00"
    """
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# ============================================================================
# 时间戳函数
# ============================================================================

def now_timestamp() -> float:
    """
    获取当前 Unix 时间戳（秒）

    Returns:
        Unix 时间戳
    """
    return _time.time()


def datetime_to_timestamp(dt: Optional[datetime]) -> Optional[float]:
    """
    将 datetime 转换为 Unix 时间戳

    Args:
        dt: 要转换的 datetime

    Returns:
        Unix 时间戳，输入为 None 时返回 None
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = ensure_tz(dt, default_to_utc=True)
    return dt.timestamp()


def timestamp_to_datetime(ts: Optional[float], to_config_tz: bool = True) -> Optional[datetime]:
    """
    将 Unix 时间戳转换为 datetime

    Args:
        ts: Unix 时间戳
        to_config_tz: 是否转换为配置时区，False 则保持 UTC

    Returns:
        datetime 对象，输入为 None 时返回 None
    """
    if ts is None:
        return None
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    if to_config_tz:
        return dt.astimezone(get_zoneinfo())
    return dt


# ============================================================================
# 日期相关辅助函数
# ============================================================================

def get_current_date() -> str:
    """
    获取当前日期字符串（配置时区）

    Returns:
        YYYY-MM-DD 格式的日期字符串
    """
    return format_date_short(now_config_tz())


def get_current_date_compact() -> str:
    """
    获取当前紧凑日期字符串（配置时区）

    Returns:
        YYYYMMDD 格式的日期字符串
    """
    return format_date_compact(now_config_tz())


def get_current_datetime_str() -> str:
    """
    获取当前日期时间字符串（配置时区）

    Returns:
        YYYY-MM-DD HH:MM:SS 格式的字符串
    """
    return format_datetime(now_config_tz())


# ============================================================================
# 导出
# ============================================================================

__all__ = [
    # 基础时间获取
    "now_utc",
    "now_config_tz",
    # 时区转换
    "to_utc",
    "to_config_tz",
    "ensure_tz",
    # 格式化
    "format_iso",
    "format_date_short",
    "format_date_compact",
    "format_datetime",
    # 时间戳
    "now_timestamp",
    "datetime_to_timestamp",
    "timestamp_to_datetime",
    # 辅助函数
    "get_current_date",
    "get_current_date_compact",
    "get_current_datetime_str",
]
