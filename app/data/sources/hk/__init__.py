"""港股数据源入口 — Provider/Adapter 工厂 + 能力注册。"""

from typing import Optional

from app.data.sources.base.provider import BaseProvider
from app.data.sources.base.adapter import BaseAdapter


def get_hk_provider(source_name: str) -> Optional[BaseProvider]:
    if source_name == "tushare_hk":
        from .tushare_hk.provider import TushareHKProvider
        return TushareHKProvider()
    elif source_name in ("akshare", "akshare_hk"):
        from .akshare_hk.provider import AKShareHKProvider
        return AKShareHKProvider()
    elif source_name in ("yfinance", "yfinance_hk"):
        from .yfinance_hk.provider import YFinanceHKProvider
        return YFinanceHKProvider()
    elif source_name == "tencent_hk":
        from .tencent_hk.provider import TencentHKProvider
        return TencentHKProvider()
    return None


def get_hk_adapter(source_name: str) -> Optional[BaseAdapter]:
    if source_name == "tushare_hk":
        from .tushare_hk.adapter import TushareHKAdapter
        return TushareHKAdapter()
    elif source_name in ("akshare", "akshare_hk"):
        from .akshare_hk.adapter import AKShareHKAdapter
        return AKShareHKAdapter()
    elif source_name in ("yfinance", "yfinance_hk"):
        from .yfinance_hk.adapter import YFinanceHKAdapter
        return YFinanceHKAdapter()
    elif source_name == "tencent_hk":
        from .tencent_hk.adapter import TencentHKAdapter
        return TencentHKAdapter()
    return None


def register_hk_sources(registry) -> None:
    """将港股数据源注册到能力注册表。"""
    from app.data.schema.base.enums import SupportLevel

    sources = {
        "tushare_hk": {
            "basic_info": SupportLevel.FULL,
            "trade_calendar": SupportLevel.FULL,
            "daily_quotes": SupportLevel.FULL,
            "daily_indicators": SupportLevel.FULL,
            "adj_factors": SupportLevel.FULL,
            "financial_data": SupportLevel.FULL,
            "market_quotes": SupportLevel.FULL,
        },
        "akshare_hk": {
            "basic_info": SupportLevel.FULL,
            "daily_quotes": SupportLevel.FULL,
            "daily_indicators": SupportLevel.PARTIAL,
            "corporate_actions": SupportLevel.FULL,
            "news": SupportLevel.FULL,
            "market_quotes": SupportLevel.FULL,
        },
        "yfinance_hk": {
            "basic_info": SupportLevel.PARTIAL,
            "daily_quotes": SupportLevel.FULL,
            "corporate_actions": SupportLevel.PARTIAL,
            "financial_data": SupportLevel.PARTIAL,
        },
        "tencent_hk": {
            "market_quotes": SupportLevel.FULL,
        },
    }

    for source_name, domains in sources.items():
        for domain, level in domains.items():
            registry.register("HK", domain, source_name, level)
