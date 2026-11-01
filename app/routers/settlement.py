"""
决策结算记分卡 REST API
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.routers.auth_db import get_current_user
from app.core.response import ok
from app.services.settlement_service import get_settlement_service

router = APIRouter(prefix="/api/settlement", tags=["Settlement"])
logger = logging.getLogger(__name__)

_VALID_CHANNEL = ("online", "backtest", "all")
_VALID_STATUS = ("pending", "settled", "unfillable")
_VALID_SIGNAL = ("Buy", "Sell", "Hold")
_VALID_ERROR_TYPE = ("direction_wrong", "unfillable")
_VALID_HORIZON = ("short", "mid", "long")


@router.get("/scorecard")
async def get_scorecard(
    channel: str = Query("online", description="聚合口径: online|backtest|all（默认 online）"),
    symbol: Optional[str] = Query(None, description="按标的过滤"),
    months: int = Query(12, ge=1, le=120, description="统计窗口（月）"),
    horizon: Optional[str] = Query(None, description="投资期限档位 short|mid|long"),
    user: dict = Depends(get_current_user),
):
    svc = get_settlement_service()
    ch = channel if channel in _VALID_CHANNEL else "online"
    data = await svc.get_scorecard(
        channel=ch, symbol=symbol, months=months, horizon=horizon if horizon in _VALID_HORIZON else None
    )
    return ok(data=data.model_dump(), message="ok")


@router.get("/records")
async def list_records(
    symbol: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="pending|settled|unfillable"),
    signal: Optional[str] = Query(None, description="Buy|Sell|Hold"),
    error_type: Optional[str] = Query(None, description="direction_wrong|unfillable"),
    channel: Optional[str] = Query(None, description="online|backtest"),
    horizon_days: Optional[int] = Query(None, ge=1, le=250, description="持有期交易日数（7/20/60）"),
    start_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    svc = get_settlement_service()
    data = await svc.list_records(
        symbol=symbol,
        status=status if status in _VALID_STATUS else None,
        signal=signal if signal in _VALID_SIGNAL else None,
        error_type=error_type if error_type in _VALID_ERROR_TYPE else None,
        channel=channel if channel in ("online", "backtest") else None,
        horizon_days=horizon_days,
        start_date=start_date,
        end_date=end_date,
        page=page,
        page_size=page_size,
    )
    return ok(data=data.model_dump(), message="ok")


@router.get("/by-task/{task_id}")
async def get_by_task(task_id: str, user: dict = Depends(get_current_user)):
    svc = get_settlement_service()
    data = await svc.get_by_task(task_id)
    return ok(data=data, message="ok")
