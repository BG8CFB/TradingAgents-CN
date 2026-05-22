"""A 股数据管理路由 — /api/cn/data。"""

from fastapi import APIRouter, Query
from typing import Optional

router = APIRouter(prefix="/api/cn/data", tags=["CN Data Management"])


@router.get("/symbols")
async def get_cn_symbols(
    list_status: Optional[str] = Query(None, description="上市状态过滤: L/D/P"),
):
    from app.data.core.interface import DataInterface
    iface = DataInterface()
    return await iface.read("CN", "basic_info", filters={"list_status": list_status})


@router.get("/calendar")
async def get_cn_calendar(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    from app.data.core.interface import DataInterface
    iface = DataInterface()
    return await iface.read("CN", "trade_calendar", filters={
        "start_date": start_date, "end_date": end_date,
    })


@router.get("/sources/health")
async def get_cn_sources_health():
    from app.data.core.interface import DataInterface
    iface = DataInterface()
    return await iface.get_source_health("CN")


@router.get("/config/priority")
async def get_cn_priority_config():
    from app.data.core.interface import DataInterface
    iface = DataInterface()
    return await iface.get_config("priority", "CN")


@router.put("/config/priority")
async def update_cn_priority_config(config: dict):
    from app.data.core.interface import DataInterface
    iface = DataInterface()
    return await iface.update_config("priority", "CN", config)
