"""美股数据源入口 — Provider/Adapter 工厂 + 能力注册。"""

from typing import Optional

from app.data.sources.base.provider import BaseProvider
from app.data.sources.base.adapter import BaseAdapter


def get_us_provider(source_name: str) -> Optional[BaseProvider]:
    if source_name == "tushare_us":
        from .tushare_us.provider import TushareUSProvider
        return TushareUSProvider()
    elif source_name == "yfinance":
        from .yfinance.provider import YFinanceUSProvider
        return YFinanceUSProvider()
    elif source_name == "finnhub":
        from .finnhub.provider import FinnhubUSProvider
        return FinnhubUSProvider()
    elif source_name == "alpha_vantage":
        from .alpha_vantage.provider import AlphaVantageUSProvider
        return AlphaVantageUSProvider()
    return None


def get_us_adapter(source_name: str) -> Optional[BaseAdapter]:
    if source_name == "tushare_us":
        from .tushare_us.adapter import TushareUSAdapter
        return TushareUSAdapter()
    elif source_name == "yfinance":
        from .yfinance.adapter import YFinanceUSAdapter
        return YFinanceUSAdapter()
    elif source_name == "finnhub":
        from .finnhub.adapter import FinnhubUSAdapter
        return FinnhubUSAdapter()
    elif source_name == "alpha_vantage":
        from .alpha_vantage.adapter import AlphaVantageUSAdapter
        return AlphaVantageUSAdapter()
    return None


def register_us_sources(registry) -> None:
    """将美股数据源注册到能力注册表。"""
    from app.data.schema.base.enums import SupportLevel

    sources = {
        "tushare_us": {
            "basic_info": SupportLevel.PARTIAL,
            "trade_calendar": SupportLevel.FULL,
            "daily_quotes": SupportLevel.PARTIAL,
            "daily_indicators": SupportLevel.PARTIAL,
            "adj_factors": SupportLevel.FULL,
            "financial_data": SupportLevel.FULL,
        },
        "yfinance": {
            "basic_info": SupportLevel.PARTIAL,
            "daily_quotes": SupportLevel.FULL,
            "corporate_actions": SupportLevel.PARTIAL,
            "daily_indicators": SupportLevel.PARTIAL,
            "financial_data": SupportLevel.PARTIAL,
            "market_quotes": SupportLevel.FULL,
        },
        "finnhub": {
            "basic_info": SupportLevel.FULL,
            "daily_quotes": SupportLevel.FULL,
            "news": SupportLevel.FULL,
            "market_quotes": SupportLevel.FULL,
        },
        "alpha_vantage": {
            "daily_quotes": SupportLevel.PARTIAL,
            "corporate_actions": SupportLevel.PARTIAL,
            "financial_data": SupportLevel.FULL,
        },
    }

    for source_name, domains in sources.items():
        for domain, level in domains.items():
            registry.register("US", domain, source_name, level)
