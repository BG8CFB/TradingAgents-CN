"""
Market Data Tools Logic
"""
import asyncio
import json
import logging
from typing import Dict, List, Any
from app.data.manager import DataSourceManager
from app.utils.stock_utils import StockUtils, StockMarket

logger = logging.getLogger(__name__)

async def get_stock_kline_logic(manager: DataSourceManager, code: str, period: str, limit: int) -> str:
    """
    Logic for get_stock_data tool.
    Handles market identification, ability checks, and data fetching via Manager.
    """
    # 1. Identify Market
    market = StockUtils.identify_stock_market(code)

    # 2. Ability-Oriented Check (Multi-market strategy)
    if market == StockMarket.US or market == StockMarket.HONG_KONG:
        # Check if any available adapter supports this market
        # For HK market, both Tushare and AKShare are supported.
        # For US market, primarily Tushare (or others if added).

        needed_providers = ['tushare']
        if market == StockMarket.HONG_KONG:
            needed_providers.append('akshare')

        provider_avail = any(a.name in needed_providers and a.is_available() for a in manager.get_available_adapters())

        if not provider_avail:
             return json.dumps({
                "status": "error",
                "code": "MARKET_NOT_SUPPORTED",
                "message": f"Service Unavailable for {market.value} Market ({code}). No capable provider (e.g. {'/'.join(needed_providers)}) is currently active."
            }, ensure_ascii=False)

    # 3. Fetch Data (Async wrapper around blocking manager)
    try:
        # manager.get_kline_with_fallback handles DB write-through internally
        items, source = await asyncio.to_thread(
            manager.get_kline_with_fallback,
            code=code,
            period=period,
            limit=limit
        )

        if not items:
            return json.dumps({
                "status": "warning",
                "message": f"No data found for {code}."
            }, ensure_ascii=False)

        # 4. Format Output (Return JSON string)
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
