"""港股每日指标同步。"""

from ._common import sync_domain


async def sync_daily_indicators(symbol: str = None, start_date: str = None, end_date: str = None):
    return await sync_domain(
        domain="daily_indicators",
        provider_method="get_daily_indicators",
        adapter_method="adapt_daily_indicators",
        provider_kwargs_fn=lambda: {
            "symbol": symbol or "00700",
            "start_date": start_date or "2020-01-01",
            "end_date": end_date or "2099-12-31",
        },
        filter_fields=["symbol", "trade_date"],
    )
