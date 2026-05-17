"""
美股 Finnhub Provider

直接调用 finnhub-python 库获取美股数据。
"""

import logging
from typing import Any, Dict, List, Optional

from app.data.sources.base.provider import BaseProvider

logger = logging.getLogger(__name__)


def _get_finnhub_client():
    import finnhub
    from app.core.config import settings

    api_key = settings.FINNHUB_API_KEY
    if not api_key:
        raise RuntimeError("Finnhub API Key 未配置")
    return finnhub.Client(api_key=api_key)


class FinnhubUSProvider(BaseProvider):
    """美股 Finnhub Provider"""

    def __init__(self):
        super().__init__(name="finnhub_us", market="US")

    async def connect(self) -> bool:
        self.connected = True
        return True

    def is_available(self) -> bool:
        try:
            import finnhub  # noqa: F401
            from app.core.config import settings
            return bool(settings.FINNHUB_API_KEY)
        except (ImportError, Exception):
            return False

    async def get_stock_basic_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        client = _get_finnhub_client()
        profile = client.company_profile2(symbol=symbol.upper())
        if not profile:
            return None
        quote = client.quote(symbol.upper())
        result = {**profile}
        if quote and "c" in quote:
            result["current_price"] = quote["c"]
            result["previous_close"] = quote.get("pc")
            result["change"] = quote.get("d")
            result["change_percent"] = quote.get("dp")
        return result

    async def get_news(
        self, symbol: str, days: int = 2, limit: int = 50
    ) -> Optional[List[Dict[str, Any]]]:
        from datetime import timedelta
        from app.utils.timezone import now_utc

        client = _get_finnhub_client()
        end_date = now_utc()
        start_date = end_date - timedelta(days=days)
        news = client.company_news(
            symbol.upper(),
            _from=start_date.strftime("%Y-%m-%d"),
            to=end_date.strftime("%Y-%m-%d"),
        )
        return news[:limit] if news else None

    async def get_kline(
        self, symbol: str, period: str = "day", limit: int = 120
    ) -> Optional[List[Dict[str, Any]]]:
        from datetime import datetime, timedelta
        from app.utils.timezone import now_utc

        client = _get_finnhub_client()
        end_date = now_utc()
        resolution_map = {
            "day": "D", "week": "W", "month": "M",
            "5m": "5", "15m": "15", "30m": "30", "60m": "60",
        }
        resolution = resolution_map.get(period, "D")
        if period == "day":
            start_date = end_date - timedelta(days=limit)
        elif period == "week":
            start_date = end_date - timedelta(weeks=limit)
        else:
            start_date = end_date - timedelta(days=limit * 30)

        candles = client.stock_candles(
            symbol.upper(), resolution,
            int(start_date.timestamp()), int(end_date.timestamp()),
        )
        if not candles or candles.get("s") != "ok":
            return None

        kline_data = []
        for i in range(len(candles["t"])):
            date_str = datetime.fromtimestamp(candles["t"][i]).strftime("%Y-%m-%d")
            kline_data.append({
                "date": date_str, "trade_date": date_str,
                "open": float(candles["o"][i]),
                "high": float(candles["h"][i]),
                "low": float(candles["l"][i]),
                "close": float(candles["c"][i]),
                "volume": int(candles["v"][i]),
            })
        return kline_data
