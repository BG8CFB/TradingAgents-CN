"""数据同步管理 API。"""

from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.core.response import ok, fail

router = APIRouter(prefix="/api/cn/data", tags=["CN Data Sync"])


class SyncRequest(BaseModel):
    domain: str
    mode: str = "incremental"
    symbols: Optional[list[str]] = None


@router.post("/sync/{domain}")
async def trigger_sync(domain: str, request: SyncRequest):
    """手动触发指定域的同步"""
    valid_domains = [
        "trade_calendar", "basic_info", "daily_quotes",
        "daily_indicators", "adj_factors", "financial", "news",
    ]
    if domain not in valid_domains:
        return fail(message=f"不支持的域: {domain}", code=400)

    try:
        from app.worker.scheduler_setup import get_scheduler_engine

        engine = get_scheduler_engine()
        if engine:
            job_id = engine.trigger_job("cn", domain)
            return ok(data={"domain": domain, "job_id": job_id, "triggered": True})
        else:
            from app.data.core.interface import DataInterface
            di = DataInterface.get_instance()
            task_id = await di.trigger_sync("CN", domain)
            return ok(data={"domain": domain, "task_id": task_id, "triggered": True})

    except Exception as e:
        return fail(message=f"同步失败: {e}", code=500)


@router.get("/sync/status")
async def get_sync_status(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    domain: Optional[str] = None,
):
    """获取同步任务状态"""
    try:
        from app.data.core.interface import DataInterface

        di = DataInterface.get_instance()
        status = await di.get_sync_status("CN", domain)

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
async def get_sync_events(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    domain: Optional[str] = None,
    event_type: Optional[str] = None,
):
    """获取同步事件流"""
    try:
        from app.data.core.interface import DataInterface

        di = DataInterface.get_instance()
        events = await di.get_sync_events("CN", limit=page_size, domain=domain)

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
