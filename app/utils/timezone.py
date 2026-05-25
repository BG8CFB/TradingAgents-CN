"""
时区工具模块（兼容层）

所有函数已迁移到 app.utils.time_utils，本文件仅保留 re-export 以兼容旧 import 路径。
新代码请直接使用: from app.utils.time_utils import ...
"""

from app.utils.time_utils import (  # noqa: F401 — re-export
    now_utc,
    now_config_tz,
    to_utc,
    to_config_tz,
    ensure_tz,
    format_iso,
    format_date_short,
    format_date_compact,
    format_datetime,
    get_current_date,
    get_current_date_compact,
    get_current_datetime_str,
)


# 别名：旧代码可能通过 timezone.py 调用的额外名称
def get_tz_name() -> str:
    from app.engine.config.runtime_settings import get_timezone_name
    return get_timezone_name()


def get_tz():
    from app.engine.config.runtime_settings import get_zoneinfo
    return get_zoneinfo()


def now_tz():
    return now_config_tz()


def ensure_timezone(dt=None):
    return ensure_tz(dt)
