"""A 股数据同步路由 — /api/cn/data。"""

import logging
from typing import Optional, List

from fastapi import APIRouter, Query, Depends
from pydantic import BaseModel

from app.core.response import ok, fail
from app.data.core.interface import DataInterface
from app.routers.auth_db import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cn/data", tags=["CN Data Sync"])

_MARKET = "CN"

_VALID_SYNC_DOMAINS = [
    "trade_calendar", "basic_info", "daily_quotes",
    "daily_indicators", "adj_factors", "financial_data", "news",
]


class RefreshRequest(BaseModel):
    domains: Optional[List[str]] = None
    force: bool = False


class SyncTriggerRequest(BaseModel):
    domain: str
    mode: str = "incremental"
    source: Optional[str] = None


# ---------------------------------------------------------------------------
# 按需刷新
# ---------------------------------------------------------------------------


@router.post("/refresh/{symbol}")
async def refresh_cn_stock(symbol: str, req: RefreshRequest, user=Depends(get_current_user)):
    """按需刷新指定股票的数据"""
    try:
        di = DataInterface.get_instance()
        result = await di.refresh(_MARKET, symbol, domains=req.domains, force=req.force, timeout=30)

        domain_dict = {}
        for d, dr in result.domains.items():
            domain_dict[d] = {
                "status": dr.status,
                "source": dr.source,
                "fallback_from": dr.fallback_from,
                "records": dr.record_count,
                "error": dr.error,
                "latency_ms": dr.latency_ms,
            }
        return ok(data={
            "symbol": result.symbol,
            "status": result.status,
            "domains": domain_dict,
            "duration_ms": result.total_latency_ms,
            "source": result.source_used,
            "fallback_from": result.fallback_from,
            "error": result.error,
        })
    except Exception as e:
        return fail(message=f"刷新失败: {e}", code=500)


@router.get("/refresh/{symbol}/status")
async def get_refresh_status(symbol: str):
    """获取指定股票各域的新鲜度状态"""
    di = DataInterface.get_instance()
    domains = ["basic_info", "daily_quotes", "daily_indicators", "adj_factors", "financial_data", "news"]
    statuses = {}
    for domain in domains:
        try:
            result = await di.read(_MARKET, domain, symbol=symbol)
            statuses[domain] = result.get("freshness", "unknown")
        except Exception:
            statuses[domain] = "unknown"
    return ok(data={"symbol": symbol, "domains": statuses})


# ---------------------------------------------------------------------------
# 同步管理
# ---------------------------------------------------------------------------


@router.post("/sync/trigger")
async def trigger_cn_sync(req: SyncTriggerRequest, user=Depends(get_current_user)):
    """触发指定域的同步任务（通过 DataInterface）"""
    di = DataInterface.get_instance()
    task_id = await di.trigger_sync(_MARKET, req.domain)
    return ok(data={"domain": req.domain, "task_id": task_id, "triggered": True})


@router.post("/sync/{domain}")
async def trigger_sync_by_domain(domain: str, request: SyncTriggerRequest, user=Depends(get_current_user)):
    """手动触发指定域的同步（通过调度引擎或 DataInterface）"""
    if domain not in _VALID_SYNC_DOMAINS:
        return fail(message=f"不支持的域: {domain}", code=400)

    try:
        from app.worker.scheduler_setup import get_scheduler_engine
        engine = get_scheduler_engine()
        if engine:
            job_id = await engine.trigger_job("CN", domain)
            return ok(data={"domain": domain, "job_id": job_id, "triggered": bool(job_id)})

        di = DataInterface.get_instance()
        task_id = await di.trigger_sync(_MARKET, domain)
        return ok(data={"domain": domain, "task_id": task_id, "triggered": True})
    except Exception as e:
        return fail(message=f"同步失败: {e}", code=500)


@router.get("/sync/status")
async def get_cn_sync_status(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    domain: Optional[str] = None,
):
    """获取同步任务状态"""
    try:
        di = DataInterface.get_instance()
        status = await di.get_sync_status(_MARKET, domain)

        items = status if isinstance(status, list) else [status] if status else []
        total = len(items)
        start = (page - 1) * page_size
        paginated = items[start:start + page_size]

        return ok(data={
            "items": paginated,
            "total": total,
            "page": page,
            "page_size": page_size,
        })
    except Exception as e:
        return fail(message=f"查询失败: {e}", code=500)


@router.get("/sync/events")
async def get_cn_sync_events(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    domain: Optional[str] = None,
    event_type: Optional[str] = None,
):
    """获取同步事件流"""
    try:
        di = DataInterface.get_instance()
        events = await di.get_sync_events(_MARKET, limit=page_size, domain=domain)

        total = len(events) if events else 0
        start = (page - 1) * page_size
        paginated = events[start:start + page_size] if events else []

        return ok(data={
            "items": paginated,
            "total": total,
            "page": page,
            "page_size": page_size,
        })
    except Exception as e:
        return fail(message=f"查询失败: {e}", code=500)
