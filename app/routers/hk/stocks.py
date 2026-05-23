"""港股股票数据路由 — /api/hk/stocks。"""

from fastapi import APIRouter, Query
from typing import Optional

from app.data.core.interface import DataInterface

router = APIRouter(prefix="/api/hk/stocks", tags=["HK Stock Data"])

_MARKET = "HK"


@router.get("/{symbol}/quotes")
async def get_hk_stock_quotes(
    symbol: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    di = DataInterface.get_instance()
    return await di.read(_MARKET, "daily_quotes", symbol=symbol,
                         start_date=start_date, end_date=end_date)


@router.get("/{symbol}/indicators")
async def get_hk_stock_indicators(
    symbol: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    di = DataInterface.get_instance()
    return await di.read(_MARKET, "daily_indicators", symbol=symbol,
                         start_date=start_date, end_date=end_date)


@router.get("/{symbol}/financials")
async def get_hk_stock_financials(
    symbol: str,
    statement_type: Optional[str] = Query(None),
):
    di = DataInterface.get_instance()
    return await di.read(_MARKET, "financial_data", symbol=symbol,
                         filters={"statement_type": statement_type})


@router.get("/{symbol}/actions")
async def get_hk_stock_actions(
    symbol: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    di = DataInterface.get_instance()
    return await di.read(_MARKET, "corporate_actions", symbol=symbol,
                         start_date=start_date, end_date=end_date)


@router.get("/{symbol}/news")
async def get_hk_stock_news(
    symbol: str,
    limit: int = Query(20, ge=1, le=100),
):
    di = DataInterface.get_instance()
    return await di.read(_MARKET, "news", symbol=symbol,
                         filters={"limit": limit})


@router.get("/{symbol}/adj-factors")
async def get_hk_stock_adj_factors(
    symbol: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    di = DataInterface.get_instance()
    return await di.read(_MARKET, "adj_factors", symbol=symbol,
                         start_date=start_date, end_date=end_date)
