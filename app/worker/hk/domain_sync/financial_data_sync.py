"""港股财务数据同步。"""

from ._common import sync_domain


async def sync_financial_data(symbol: str = None, start_date: str = None, end_date: str = None, statement_type: str = ""):
    return await sync_domain(
        domain="financial_data",
        provider_method="get_financial_data",
        adapter_method="adapt_financial_data",
        provider_kwargs_fn=lambda: {
            "symbol": symbol or "00700",
            "start_date": start_date or "2020-01-01",
            "end_date": end_date or "2099-12-31",
            "statement_type": statement_type,
        },
        filter_fields=["symbol", "report_period", "statement_type"],
    )
