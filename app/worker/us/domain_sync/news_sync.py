"""美股新闻同步 — Finnhub 主源。"""

from ._common import sync_domain


async def sync_news(symbol: str = None, start_date: str = None, end_date: str = None):
    return await sync_domain(
        domain="news",
        provider_method="get_news",
        adapter_method="adapt_news",
        provider_kwargs_fn=lambda: {
            "symbol": symbol or "AAPL",
            "start_date": start_date or "2020-01-01",
            "end_date": end_date or "2099-12-31",
        },
        filter_fields=["content_hash"],
    )
