"""
A股同步路由（定时全量同步模式）

保留与 stock_sync / multi_source_sync 的兼容路径，
内部委托到 worker/cn/ 的同步服务。
"""

import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, BackgroundTasks
from pydantic import BaseModel, Field

from app.routers.auth_db import get_current_user
from app.core.response import ok, fail

logger = logging.getLogger("webapi")

router = APIRouter(prefix="/api/sync/cn", tags=["CN Sync"])


class CNSyncRequest(BaseModel):
    force: bool = Field(False, description="是否强制全量同步")
    preferred_sources: Optional[List[str]] = Field(None, description="优先数据源")


class CNSyncSingleRequest(BaseModel):
    symbol: str = Field(..., description="6位股票代码")
    sync_historical: bool = Field(True, description="同步历史数据")
    sync_financial: bool = Field(True, description="同步财务数据")
    data_source: str = Field("tushare", description="数据源: tushare/akshare")
    days: int = Field(30, description="回溯天数", ge=1, le=3650)


@router.get("/sources/status")
async def get_cn_sources_status():
    """A股数据源状态"""
    try:
        from app.data import reader as _data_reader
        available = _data_reader.get_available_adapters()
        result = []
        for adapter in _data_reader.get_all_adapters():
            result.append({
                "name": adapter.name,
                "priority": adapter.priority,
                "available": adapter in available,
            })
        return ok(data=result)
    except Exception as e:
        logger.error(f"获取A股数据源状态失败: {e}")
        return ok(data=[], message=str(e))


@router.post("/basic")
async def sync_cn_basic(
    request: CNSyncRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    """触发 A 股基础信息同步"""
    try:
        from app.services.multi_source_basics_sync_service import get_multi_source_sync_service
        service = await get_multi_source_sync_service()

        async def _do_sync():
            await service.sync_basic_info(force=request.force)

        background_tasks.add_task(_do_sync)
        return ok(message="A股基础信息同步已触发")
    except Exception as e:
        logger.error(f"A股基础信息同步失败: {e}")
        return fail(message=str(e))


@router.post("/single")
async def sync_cn_single(
    request: CNSyncSingleRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    """同步单只 A 股数据"""
    try:
        from app.worker.cn.tushare_sync import get_tushare_sync_service
        from app.worker.cn.akshare_sync import get_akshare_sync_service
        from app.worker.financial_data_sync_service import get_financial_sync_service

        symbol = request.symbol.strip().zfill(6)

        async def _do_sync():
            if request.data_source == "tushare":
                ts = get_tushare_sync_service()
                if request.sync_historical:
                    await ts.sync_single_stock_historical(symbol, days=request.days)
                if request.sync_financial:
                    fs = get_financial_sync_service()
                    await fs.sync_single_stock(symbol)
            elif request.data_source == "akshare":
                ak = get_akshare_sync_service()
                if request.sync_historical:
                    await ak.sync_single_stock_historical(symbol, days=request.days)

        background_tasks.add_task(_do_sync)
        return ok(message=f"股票 {symbol} 同步已触发")
    except Exception as e:
        logger.error(f"单股同步失败: {e}")
        return fail(message=str(e))
