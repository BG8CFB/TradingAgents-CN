"""美股复权因子同步 — Tushare US 唯一直供。"""

from ._common import sync_domain


async def sync_adj_factors(symbol: str = None, start_date: str = None, end_date: str = None):
    return await sync_domain(
        domain="adj_factors",
        provider_method="get_adj_factors",
        adapter_method="adapt_adj_factors",
        provider_kwargs_fn=lambda: {
            "symbol": symbol or "AAPL",
            "start_date": start_date or "2020-01-01",
            "end_date": end_date or "2099-12-31",
        },
        filter_fields=["symbol", "trade_date"],
    )
