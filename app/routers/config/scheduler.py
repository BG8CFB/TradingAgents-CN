"""
配置管理 - 调度器配置子路由（预留）

当前调度器管理端点由 app.routers.scheduler 模块提供。
此文件作为预留占位，未来如需将调度器相关配置端点
迁移到此包下，可在此处扩展。
"""

from fastapi import APIRouter

router = APIRouter(tags=["Config"])
