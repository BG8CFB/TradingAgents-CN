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
