"""
通知 REST API
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query

from app.routers.auth_db import get_current_user
from app.core.response import ok
from app.services.notifications_service import get_notifications_service

router = APIRouter(prefix="/api/notifications", tags=["Notifications"])
logger = logging.getLogger("webapi.notifications")


@router.get("")
async def list_notifications(
    status: Optional[str] = Query(None, description="状态: unread|read|all"),
    type: Optional[str] = Query(None, description="类型: analysis|alert|system"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user)
):
    svc = get_notifications_service()
    s = status if status in ("read","unread") else None
    t = type if type in ("analysis","alert","system") else None
    data = await svc.list(user_id=user["id"], status=s, ntype=t, page=page, page_size=page_size)
    return ok(data=data.model_dump(), message="ok")


@router.get("/unread_count")
async def get_unread_count(user: dict = Depends(get_current_user)):
    svc = get_notifications_service()
    cnt = await svc.unread_count(user_id=user["id"])
    return ok(data={"count": cnt})


@router.post("/{notif_id}/read")
async def mark_read(notif_id: str, user: dict = Depends(get_current_user)):
    svc = get_notifications_service()
    ok_flag = await svc.mark_read(user_id=user["id"], notif_id=notif_id)
    if not ok_flag:
        raise HTTPException(status_code=404, detail="Notification not found")
    return ok()


@router.post("/read_all")
async def mark_all_read(user: dict = Depends(get_current_user)):
    svc = get_notifications_service()
    n = await svc.mark_all_read(user_id=user["id"])
    return ok(data={"updated": n})