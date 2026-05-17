"""
同步路由入口（按市场拆分）

A 股: cn_sync  — 定时全量同步
港股: hk_sync  — 按需缓存模式
美股: us_sync  — 按需缓存模式
"""

from fastapi import APIRouter

from app.routers.sync.cn_sync import router as cn_router
from app.routers.sync.hk_sync import router as hk_router
from app.routers.sync.us_sync import router as us_router

router = APIRouter()
router.include_router(cn_router)
router.include_router(hk_router)
router.include_router(us_router)

__all__ = ["router"]
