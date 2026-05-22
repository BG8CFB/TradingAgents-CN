"""港股市场快照同步。"""

from ._common import sync_domain


async def sync_market_quotes(symbols: list = None):
    return await sync_domain(
        domain="market_quotes",
        provider_method="get_market_quotes",
        adapter_method="adapt_market_quotes",
        provider_kwargs_fn=lambda: {"symbols": symbols},
        filter_fields=["symbol"],
    )
