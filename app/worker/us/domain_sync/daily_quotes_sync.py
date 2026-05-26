"""美股日线行情同步。"""

from ._common import sync_domain


async def sync_daily_quotes(symbol: str, start_date: str = None, end_date: str = None):
    if not symbol:
        raise ValueError("必须指定 symbol 参数，不能为空")
    return await sync_domain(
        domain="daily_quotes",
        provider_method="get_daily_quotes",
        adapter_method="adapt_daily_quotes",
        provider_kwargs_fn=lambda: {
            "symbol": symbol,
            "start_date": start_date or "2020-01-01",
            "end_date": end_date or "2099-12-31",
        },
        filter_fields=["symbol", "trade_date"],
    )
