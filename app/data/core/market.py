"""市场相关工具函数。"""

from datetime import datetime, date
from typing import Optional
from zoneinfo import ZoneInfo

from app.data.schema.base.markets import MarketType, MARKET_META


def get_market_timezone(market: str):
    """获取市场时区。"""
    meta = MARKET_META.get(MarketType(market))
    if meta:
        return ZoneInfo(meta.timezone)
    return ZoneInfo("UTC")


def to_market_time(utc_dt: datetime, market: str) -> datetime:
    """UTC 时间转为市场本地时间。"""
    tz = get_market_timezone(market)
    return utc_dt.astimezone(tz)


def to_utc(market_dt: datetime, market: str) -> datetime:
    """市场本地时间转为 UTC。"""
    tz = get_market_timezone(market)
    localized = market_dt.replace(tzinfo=tz)
    return localized.astimezone(ZoneInfo("UTC"))


async def is_trading_day(market: str, target_date: Optional[date] = None) -> bool:
    """判断是否为交易日（查询 trade_calendar）。"""
    if target_date is None:
        target_date = date.today()

    from app.data.storage.mongo.repositories.trade_calendar_repo import TradeCalendarRepo

    meta = MARKET_META.get(MarketType(market))
    if not meta:
        return False

    repo = TradeCalendarRepo()
    exchange = meta.exchanges[0] if meta.exchanges else ""
    return await repo.is_trading_day(target_date.isoformat(), exchange, market)


def is_dst(market: str) -> bool:
    """判断市场是否处于夏令时。"""
    tz = get_market_timezone(market)
    now = datetime.now(tz)
    return bool(now.dst())
