"""
数据同步管理 API
"""

import asyncio
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.core.response import ok, fail

router = APIRouter(prefix="/api/cn/data", tags=["CN Data Sync"])


class SyncRequest(BaseModel):
    domain: str
    mode: str = "incremental"  # incremental / full
    symbols: Optional[list[str]] = None


@router.post("/sync/{domain}")
async def trigger_sync(domain: str, request: SyncRequest):
    """手动触发指定域的同步"""
    from app.worker.cn.cn_sync_orchestrator import get_cn_sync_orchestrator

    valid_domains = [
        "trade_calendar", "basic_info", "daily_quotes",
        "daily_indicators", "adj_factors", "financial",
    ]
    if domain not in valid_domains:
        return fail(message=f"不支持的域: {domain}", code=400)

    try:
        orchestrator = get_cn_sync_orchestrator()
        sync = orchestrator._domain_syncs.get(domain)
        if not sync:
            return fail(message=f"域 {domain} 无同步模块", code=400)

        if request.symbols:
            results = []
            for symbol in request.symbols[:50]:  # 限制最多 50 只
                result = await sync.sync(symbol=symbol)
                results.append(result.to_dict())
            return ok(data={"domain": domain, "results": results})
        else:
            result = await sync.sync()
            return ok(data=result.to_dict())

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
        from app.core.database import get_database
        from app.data.schema.collections import get_collection_name

        db = await get_database()
        collection = db[get_collection_name("CN", "sync_checkpoints")]

        query = {}
        if domain:
            query["domain"] = domain

        total = await collection.count_documents(query)
        cursor = collection.find(query).sort("last_sync_time", -1).skip((page - 1) * page_size).limit(page_size)
        items = await cursor.to_list(length=page_size)

        return ok(data={
            "items": items,
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
        from app.core.database import get_database
        from app.data.schema.collections import get_collection_name

        db = await get_database()
        collection = db[get_collection_name("CN", "sync_events")]

        query = {}
        if domain:
            query["domain"] = domain
        if event_type:
            query["event_type"] = event_type

        total = await collection.count_documents(query)
        cursor = collection.find(query).sort("updated_at", -1).skip((page - 1) * page_size).limit(page_size)
        items = await cursor.to_list(length=page_size)

        return ok(data={
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        })

    except Exception as e:
        return fail(message=f"查询失败: {e}", code=500)
