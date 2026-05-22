"""港股数据管理路由 — /api/hk/data。"""

from fastapi import APIRouter, Query
from typing import Optional

router = APIRouter(prefix="/api/hk/data", tags=["HK Data Management"])


@router.get("/symbols")
async def get_hk_symbols(
    list_status: Optional[str] = Query(None),
):
    from app.data.core.interface import DataInterface
    iface = DataInterface()
    return await iface.read("HK", "basic_info", filters={"list_status": list_status})


@router.get("/calendar")
async def get_hk_calendar(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    from app.data.core.interface import DataInterface
    iface = DataInterface()
    return await iface.read("HK", "trade_calendar", filters={
        "start_date": start_date, "end_date": end_date,
    })


@router.get("/sources/health")
async def get_hk_sources_health():
    from app.data.core.interface import DataInterface
    iface = DataInterface()
    return await iface.get_source_health("HK")


@router.get("/config/priority")
async def get_hk_priority_config():
    from app.data.core.interface import DataInterface
    iface = DataInterface()
    return await iface.get_config("priority", "HK")


@router.put("/config/priority")
async def update_hk_priority_config(config: dict):
    from app.data.core.interface import DataInterface
    iface = DataInterface()
    return await iface.update_config("priority", "HK", config)
