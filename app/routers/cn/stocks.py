"""A 股股票数据路由 — /api/cn/stocks。"""

from fastapi import APIRouter, Query
from typing import Optional

router = APIRouter(prefix="/api/cn/stocks", tags=["CN Stock Data"])


@router.get("/{symbol}/quotes")
async def get_cn_stock_quotes(
    symbol: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    from app.data.core.interface import DataInterface
    iface = DataInterface()
    return await iface.read("CN", "daily_quotes", symbol=symbol,
                            filters={"start_date": start_date, "end_date": end_date})


@router.get("/{symbol}/indicators")
async def get_cn_stock_indicators(
    symbol: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    from app.data.core.interface import DataInterface
    iface = DataInterface()
    return await iface.read("CN", "daily_indicators", symbol=symbol,
                            filters={"start_date": start_date, "end_date": end_date})


@router.get("/{symbol}/financials")
async def get_cn_stock_financials(
    symbol: str,
    statement_type: Optional[str] = Query(None),
    report_period: Optional[str] = Query(None),
):
    from app.data.core.interface import DataInterface
    iface = DataInterface()
    return await iface.read("CN", "financial_data", symbol=symbol,
                            filters={"statement_type": statement_type, "report_period": report_period})


@router.get("/{symbol}/news")
async def get_cn_stock_news(
    symbol: str,
    limit: int = Query(20, ge=1, le=100),
):
    from app.data.core.interface import DataInterface
    iface = DataInterface()
    return await iface.read("CN", "news", symbol=symbol, filters={"limit": limit})
