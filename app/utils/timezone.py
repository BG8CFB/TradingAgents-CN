"""
app 层时区工具模块

依赖统一的时间工具模块 tradingagents.utils.time_utils
保持向后兼容的 API
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

# 从统一工具模块导入
from tradingagents.utils.time_utils import (
    now_utc,
    now_config_tz,
    to_utc,
    to_config_tz as _to_config_tz,
    ensure_tz as _ensure_tz,
    format_iso,
    format_date_short,
    format_date_compact,
    format_datetime,
    get_current_date,
    get_current_date_compact,
    get_current_datetime_str,
)

# 从运行时配置导入
from tradingagents.config.runtime_settings import get_timezone_name, get_zoneinfo


# ============================================================================
# 向后兼容的函数别名
# ============================================================================

def get_tz_name() -> str:
    """获取配置的时区名称"""
    return get_timezone_name()


def get_tz():
    """获取 ZoneInfo 对象"""
    return get_zoneinfo()


def now_tz() -> datetime:
    """当前配置时区时间（向后兼容）"""
    return now_config_tz()


def ensure_timezone(dt: Optional[datetime]) -> Optional[datetime]:
    """确保 datetime 包含时区信息（向后兼容）"""
    return _ensure_tz(dt)


# 重新导出 to_config_tz 函数（向后兼容）
def to_config_tz(dt: Optional[datetime]) -> Optional[datetime]:
    """将 datetime 转换为配置时区（向后兼容）"""
    return _to_config_tz(dt)


# 重新导出 ensure_tz 函数（向后兼容）
def ensure_tz(dt: Optional[datetime]) -> Optional[datetime]:
    """确保 datetime 包含时区信息（向后兼容）"""
    return _ensure_tz(dt)


# ============================================================================
# 导出所有函数
# ============================================================================

__all__ = [
    # 兼容旧代码
    "get_tz_name",
    "get_tz",
    "now_tz",
    "to_config_tz",
    "ensure_timezone",
    # 新增：从统一模块导出
    "now_utc",
    "now_config_tz",
    "to_utc",
    "ensure_tz",
    "format_iso",
    "format_date_short",
    "format_date_compact",
    "format_datetime",
    "get_current_date",
    "get_current_date_compact",
    "get_current_datetime_str",
]
