"""美股公司行为同步 — yfinance 主源。"""

from ._common import sync_domain


async def sync_corporate_actions(symbol: str = None, start_date: str = None, end_date: str = None):
    return await sync_domain(
        domain="corporate_actions",
        provider_method="get_corporate_actions",
        adapter_method="adapt_corporate_actions",
        provider_kwargs_fn=lambda: {
            "symbol": symbol or "AAPL",
            "start_date": start_date or "2020-01-01",
            "end_date": end_date or "2099-12-31",
        },
        filter_fields=["symbol", "ex_date", "action_type"],
    )
