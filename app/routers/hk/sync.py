"""港股数据同步路由 — /api/hk/data。"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, List

router = APIRouter(prefix="/api/hk/data", tags=["HK Data Sync"])


class RefreshRequest(BaseModel):
    domains: Optional[List[str]] = None
    force: bool = False


class SyncTriggerRequest(BaseModel):
    domain: str
    source: Optional[str] = None
    full_sync: bool = False


@router.post("/refresh/{symbol}")
async def refresh_hk_stock(symbol: str, req: RefreshRequest):
    from app.data.core.interface import DataInterface
    iface = DataInterface()
    return await iface.refresh("HK", symbol, domains=req.domains, force=req.force)


@router.post("/sync/trigger")
async def trigger_hk_sync(req: SyncTriggerRequest):
    from app.data.core.interface import DataInterface
    iface = DataInterface()
    return await iface.trigger_sync("HK", req.domain, source=req.source, full_sync=req.full_sync)


@router.get("/sync/status")
async def get_hk_sync_status(domain: Optional[str] = None):
    from app.data.core.interface import DataInterface
    iface = DataInterface()
    return await iface.get_sync_status("HK", domain=domain)


@router.get("/sync/events")
async def get_hk_sync_events(
    domain: Optional[str] = None,
    limit: int = 50,
):
    from app.data.core.interface import DataInterface
    iface = DataInterface()
    return await iface.get_sync_status("HK", domain=domain, events=True, limit=limit)
