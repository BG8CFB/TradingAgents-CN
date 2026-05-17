"""
Market Data Tools Logic
"""
import asyncio
import json
import logging
from app.utils.stock_utils import StockUtils, StockMarket

logger = logging.getLogger(__name__)


async def get_stock_kline_logic(reader_mod, code: str, period: str, limit: int) -> str:
    """
    Logic for get_stock_data tool.
    """
    market = StockUtils.identify_stock_market(code)

    if market == StockMarket.US or market == StockMarket.HONG_KONG:
        needed_providers = ['tushare']
        if market == StockMarket.HONG_KONG:
            needed_providers.append('akshare')

        available = reader_mod.get_available_adapters()
        provider_avail = any(
            a.name in needed_providers and a.is_available() for a in available
        )

        if not provider_avail:
            return json.dumps({
                "status": "error",
                "code": "MARKET_NOT_SUPPORTED",
                "message": f"Service Unavailable for {market.value} Market ({code}). No capable provider is currently active."
            }, ensure_ascii=False)

    try:
        items, source = await asyncio.to_thread(
            reader_mod.get_kline_with_fallback,
            code=code,
            period=period,
            limit=limit
        )

        if not items:
            return json.dumps({
                "status": "warning",
                "message": f"No data found for {code}."
            }, ensure_ascii=False)

        result = {
            "code": code,
            "market": market.value,
            "source": source,
            "count": len(items),
            "data": items
        }
        return json.dumps(result, ensure_ascii=False, default=str)

    except Exception as e:
        logger.error(f"Error in get_stock_kline_logic: {e}")
        return json.dumps({
            "status": "error",
            "message": str(e)
        }, ensure_ascii=False)
