"""美股基础信息同步 — Finnhub 全市场列表主源。"""

from ._common import sync_domain


async def sync_basic_info():
    return await sync_domain(
        domain="basic_info",
        provider_method="get_stock_list",
        adapter_method="adapt_basic_info",
        filter_fields=["symbol"],
    )
