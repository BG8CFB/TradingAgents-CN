#!/usr/bin/env python3
"""
历史数据查询API
提供统一的历史K线数据查询接口
"""
import logging
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel, Field

from app.routers.auth_db import get_current_user
from app.data.core.interface import DataInterface
from app.utils.timezone import now_utc, format_iso
from app.core.response import safe_error_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/historical-data", tags=["Historical Data"])


class HistoricalDataQuery(BaseModel):
    """历史数据查询请求"""
    symbol: str = Field(..., description="股票代码")
    start_date: Optional[str] = Field(None, description="开始日期 (YYYY-MM-DD)")
    end_date: Optional[str] = Field(None, description="结束日期 (YYYY-MM-DD)")
    data_source: Optional[str] = Field(None, description="数据源 (tushare/akshare/baostock)")
    period: Optional[str] = Field(None, description="数据周期 (daily/weekly/monthly)")
    limit: Optional[int] = Field(None, ge=1, le=1000, description="限制返回数量")


class HistoricalDataResponse(BaseModel):
    """历史数据响应"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


def _detect_market(symbol: str) -> str:
    """根据代码格式推断市场。"""
    s = str(symbol).strip()
    if "." in s:
        suffix = s.split(".")[-1].upper()
        if suffix == "HK":
            return "HK"
        return "US"
    if s.isdigit() and len(s) <= 6:
        return "CN"
    return "CN"


async def _query_daily_quotes(
    symbol: str, market: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    data_source: Optional[str] = None,
    period: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[Dict]:
    """通过 DataInterface 查询日线行情。"""
    di = DataInterface.get_instance()
    result = await di.read(market, symbol, "daily_quotes",
                           start_date=start_date, end_date=end_date)
    records = result.get("data", [])

    # 客户端过滤
    if data_source:
        records = [r for r in records if r.get("data_source") == data_source]
    if period and period != "daily":
        records = [r for r in records if r.get("period") == period]
    if limit:
        records = records[:limit]

    return records


async def _get_daily_quotes_stats(market: str) -> Dict[str, Any]:
    """获取日线行情统计信息（通过 service 层）。"""
    from app.services.data_dashboard_service import get_daily_quotes_stats
    return await get_daily_quotes_stats(market)


@router.get("/query/{symbol}", response_model=HistoricalDataResponse)
async def get_historical_data(
    symbol: str,
    start_date: Optional[str] = Query(None, description="开始日期 (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="结束日期 (YYYY-MM-DD)"),
    data_source: Optional[str] = Query(None, description="数据源 (tushare/akshare/baostock)"),
    period: Optional[str] = Query(None, description="数据周期 (daily/weekly/monthly)"),
    limit: Optional[int] = Query(None, ge=1, le=1000, description="限制返回数量"),
    current_user: dict = Depends(get_current_user)
):
    """查询股票历史数据"""
    try:
        market = _detect_market(symbol)
        results = await _query_daily_quotes(
            symbol, market, start_date, end_date, data_source, period, limit
        )

        response_data = {
            "symbol": symbol,
            "count": len(results),
            "query_params": {
                "start_date": start_date,
                "end_date": end_date,
                "data_source": data_source,
                "period": period,
                "limit": limit,
            },
            "records": results,
        }

        return HistoricalDataResponse(
            success=True,
            message=f"查询成功，返回 {len(results)} 条记录",
            data=response_data,
        )

    except Exception as e:
        logger.error(f"查询历史数据失败 {symbol}: {e}")
        raise HTTPException(status_code=500, detail=safe_error_message(e, "查询失败"))


@router.post("/query", response_model=HistoricalDataResponse)
async def query_historical_data(request: HistoricalDataQuery, current_user: dict = Depends(get_current_user)):
    """POST方式查询历史数据"""
    try:
        market = _detect_market(request.symbol)
        results = await _query_daily_quotes(
            request.symbol, market,
            request.start_date, request.end_date,
            request.data_source, request.period, request.limit,
        )

        response_data = {
            "symbol": request.symbol,
            "count": len(results),
            "query_params": request.dict(),
            "records": results,
        }

        return HistoricalDataResponse(
            success=True,
            message=f"查询成功，返回 {len(results)} 条记录",
            data=response_data,
        )

    except Exception as e:
        logger.error(f"查询历史数据失败 {request.symbol}: {e}")
        raise HTTPException(status_code=500, detail=safe_error_message(e, "查询失败"))


@router.get("/latest-date/{symbol}")
async def get_latest_date(
    symbol: str,
    data_source: str = Query(..., description="数据源 (tushare/akshare/baostock)"),
    current_user: dict = Depends(get_current_user)
):
    """获取股票最新数据日期"""
    try:
        market = _detect_market(symbol)
        di = DataInterface.get_instance()
        result = await di.read(market, symbol, "daily_quotes")
        records = result.get("data", [])
        latest_date = None
        if records:
            if isinstance(records, list):
                latest_date = records[0].get("trade_date") if records else None
            elif isinstance(records, dict):
                latest_date = records.get("trade_date")

        return {
            "success": True,
            "data": {
                "symbol": symbol,
                "data_source": data_source,
                "latest_date": latest_date,
            },
            "message": "查询成功",
        }

    except Exception as e:
        logger.error(f"获取最新日期失败 {symbol}: {e}")
        raise HTTPException(status_code=500, detail=safe_error_message(e, "查询失败"))


@router.get("/statistics")
async def get_data_statistics(current_user: dict = Depends(get_current_user)):
    """获取历史数据统计信息"""
    try:
        stats = await _get_daily_quotes_stats("CN")

        return {
            "success": True,
            "data": stats,
            "message": "统计信息获取成功",
        }

    except Exception as e:
        logger.error(f"获取统计信息失败: {e}")
        raise HTTPException(status_code=500, detail=safe_error_message(e, "获取统计信息失败"))


@router.get("/compare/{symbol}")
async def compare_data_sources(
    symbol: str,
    trade_date: str = Query(..., description="交易日期 (YYYY-MM-DD)"),
    current_user: dict = Depends(get_current_user)
):
    """对比不同数据源的同一股票同一日期的数据"""
    try:
        market = _detect_market(symbol)
        sources = ["tushare", "akshare", "baostock"]
        comparison = {}

        for source in sources:
            results = await _query_daily_quotes(
                symbol, market,
                start_date=trade_date, end_date=trade_date,
                data_source=source, limit=1,
            )
            comparison[source] = results[0] if results else None

        return {
            "success": True,
            "data": {
                "symbol": symbol,
                "trade_date": trade_date,
                "comparison": comparison,
                "available_sources": [k for k, v in comparison.items() if v is not None],
            },
            "message": "数据对比完成",
        }

    except Exception as e:
        logger.error(f"数据对比失败 {symbol}: {e}")
        raise HTTPException(status_code=500, detail=safe_error_message(e, "数据对比失败"))


@router.get("/health")
async def health_check():
    """健康检查"""
    try:
        stats = await _get_daily_quotes_stats("CN")

        return {
            "success": True,
            "data": {
                "service": "历史数据服务",
                "status": "healthy",
                "total_records": stats["total_records"],
                "total_symbols": stats["total_symbols"],
                "last_check": format_iso(now_utc()),
            },
            "message": "服务正常",
        }

    except Exception as e:
        logger.error(f"健康检查失败: {e}")
        return {
            "success": False,
            "data": {
                "service": "历史数据服务",
                "status": "unhealthy",
                "error": str(e),
                "last_check": format_iso(now_utc()),
            },
            "message": "服务异常",
        }
