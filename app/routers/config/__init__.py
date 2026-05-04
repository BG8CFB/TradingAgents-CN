"""
配置管理API路由包

将原 config.py 拆分为 5 个子模块：
- llm: 大模型厂家 & LLM 配置管理
- data_sources: 数据源 & 数据源分组管理
- system: 系统配置、设置、导出导入、数据库配置
- markets: 市场分类 & 模型目录管理
- scheduler: 调度器配置（预留）
"""

from fastapi import APIRouter

from app.routers.config.llm import router as llm_router
from app.routers.config.data_sources import router as data_sources_router
from app.routers.config.system import router as system_router
from app.routers.config.markets import router as markets_router
from app.routers.config.scheduler import router as scheduler_router

router = APIRouter(prefix="/api/config", tags=["Config"])

router.include_router(llm_router)
router.include_router(data_sources_router)
router.include_router(system_router)
router.include_router(markets_router)
router.include_router(scheduler_router)
