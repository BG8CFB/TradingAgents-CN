"""美股股票数据路由 — /api/us/stocks。"""

from fastapi import APIRouter, Query
from typing import Optional

router = APIRouter(prefix="/api/us/stocks", tags=["US Stock Data"])


@router.get("/{symbol}/quotes")
async def get_us_stock_quotes(
    symbol: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    from app.data.core.interface import DataInterface
    iface = DataInterface()
    return await iface.read("US", "daily_quotes", symbol=symbol,
                            filters={"start_date": start_date, "end_date": end_date})


@router.get("/{symbol}/indicators")
async def get_us_stock_indicators(
    symbol: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    from app.data.core.interface import DataInterface
    iface = DataInterface()
    return await iface.read("US", "daily_indicators", symbol=symbol,
                            filters={"start_date": start_date, "end_date": end_date})


@router.get("/{symbol}/financials")
async def get_us_stock_financials(
    symbol: str,
    statement_type: Optional[str] = Query(None),
):
    from app.data.core.interface import DataInterface
    iface = DataInterface()
    return await iface.read("US", "financial_data", symbol=symbol,
                            filters={"statement_type": statement_type})


@router.get("/{symbol}/actions")
async def get_us_stock_actions(
    symbol: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    from app.data.core.interface import DataInterface
    iface = DataInterface()
    return await iface.read("US", "corporate_actions", symbol=symbol,
                            filters={"start_date": start_date, "end_date": end_date})


@router.get("/{symbol}/news")
async def get_us_stock_news(
    symbol: str,
    limit: int = Query(20, ge=1, le=100),
):
    from app.data.core.interface import DataInterface
    iface = DataInterface()
    return await iface.read("US", "news", symbol=symbol, filters={"limit": limit})
