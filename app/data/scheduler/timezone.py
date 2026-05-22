"""时区工具 — 处理 ET 夏令时。"""

from datetime import datetime
from zoneinfo import ZoneInfo


def to_market_time(utc_dt: datetime, market: str) -> datetime:
    """UTC 转市场本地时间。"""
    tz_map = {
        "CN": "Asia/Shanghai",
        "HK": "Asia/Hong_Kong",
        "US": "America/New_York",
    }
    tz_name = tz_map.get(market, "UTC")
    return utc_dt.astimezone(ZoneInfo(tz_name))


def to_utc(market_dt: datetime, market: str) -> datetime:
    """市场本地时间转 UTC。"""
    tz_map = {
        "CN": "Asia/Shanghai",
        "HK": "Asia/Hong_Kong",
        "US": "America/New_York",
    }
    tz_name = tz_map.get(market, "UTC")
    tz = ZoneInfo(tz_name)
    if market_dt.tzinfo is None:
        market_dt = market_dt.replace(tzinfo=tz)
    return market_dt.astimezone(ZoneInfo("UTC"))


def is_dst(market: str) -> bool:
    """判断是否夏令时。"""
    tz_map = {
        "US": "America/New_York",
    }
    tz_name = tz_map.get(market)
    if not tz_name:
        return False
    now = datetime.now(ZoneInfo(tz_name))
    return bool(now.dst())
