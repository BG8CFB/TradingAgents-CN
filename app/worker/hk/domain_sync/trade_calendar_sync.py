"""港股交易日历同步。"""

from ._common import sync_domain


async def sync_trade_calendar(exchange: str = "HKEX", start_date: str = None, end_date: str = None):
    return await sync_domain(
        domain="trade_calendar",
        provider_method="get_trade_calendar",
        adapter_method="adapt_trade_calendar",
        provider_kwargs_fn=lambda: {
            "exchange": exchange,
            "start_date": start_date or "2020-01-01",
            "end_date": end_date or "2099-12-31",
        },
        filter_fields=["exchange", "cal_date"],
    )
