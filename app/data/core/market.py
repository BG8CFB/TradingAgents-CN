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


async def get_latest_trade_day(
    market: str, before: Optional[date] = None
) -> Optional[date]:
    """查询 <= before（默认今天）的最近一个交易日。

    无交易日历数据时返回 None，由调用方决定兜底策略。
    """
    if before is None:
        before = date.today()

    from datetime import timedelta

    from app.data.storage.mongo.repositories.trade_calendar_repo import TradeCalendarRepo

    meta = MARKET_META.get(MarketType(market))
    if not meta:
        return None

    repo = TradeCalendarRepo()
    exchange = meta.exchanges[0] if meta.exchanges else ""
    # 向前取 30 天窗口，足以覆盖任意节假日连休
    start = before - timedelta(days=30)
    docs = await repo.get_range(
        exchange, market, start.isoformat(), before.isoformat()
    )
    open_days = [
        d["cal_date"] for d in docs
        if d.get("is_open") and d.get("cal_date")
    ]
    if not open_days:
        return None
    latest = max(open_days)
    try:
        return date.fromisoformat(latest)
    except ValueError:
        return None


def is_dst(market: str) -> bool:
    """判断市场是否处于夏令时。"""
    tz = get_market_timezone(market)
    now = datetime.now(tz)
    return bool(now.dst())
