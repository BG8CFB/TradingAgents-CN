"""知识库路由 — 语料概览 / 索引状态与重建 / 检索测试 / 引用计数。

数据访问全部经 app/services/knowledge_service（不触碰数据层内部模块）。
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.response import ok
from app.routers.auth_db import get_current_user, require_admin
from app.services import knowledge_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge", tags=["Knowledge"])


class SearchRequest(BaseModel):
    market: str = Field(default="CN", description="市场 (CN/HK/US)")
    symbol: str = Field(..., description="股票代码")
    query: str = Field(..., description="检索关键词或自然语言")
    as_of: Optional[str] = Field(None, description="截止日期 YYYY-MM-DD（防前视）")
    start_date: Optional[str] = Field(None, description="起始日期（时间窗）")
    top_k: int = Field(default=6, ge=1, le=20)
    types: Optional[List[str]] = Field(None, description="语料类型过滤（如 news/announcement）")


class RebuildRequest(BaseModel):
    market: Optional[str] = Field(None, description="市场；空 = 全部市场")


@router.get("/overview")
async def get_overview(current_user: dict = Depends(get_current_user)):
    """语料概览 + 索引状态 + 向量模型配置（概览/索引状态两 tab 共用）"""
    try:
        return ok(await knowledge_service.get_overview())
    except Exception as e:
        logger.error(f"知识库概览获取失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="知识库概览获取失败")


@router.post("/search")
async def search(
    request: SearchRequest,
    current_user: dict = Depends(get_current_user),
):
    """检索测试：symbol + 关键词 + 时间窗 → top-K 与出处"""
    if not request.symbol.strip() or not request.query.strip():
        raise HTTPException(status_code=422, detail="symbol 与 query 不能为空")
    if request.market.upper() not in ("CN", "HK", "US"):
        raise HTTPException(status_code=422, detail="market 必须是 CN/HK/US")
    try:
        results = await knowledge_service.search(
            request.market.upper(),
            request.symbol.strip(),
            request.query.strip(),
            as_of=request.as_of,
            top_k=request.top_k,
            types=request.types,
            start_date=request.start_date,
        )
        return ok({"results": results, "count": len(results)})
    except Exception as e:
        logger.error(f"知识库检索失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="知识库检索失败")


@router.post("/index")
async def run_index_now(
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(require_admin),
):
    """手动触发一轮增量索引（后台执行，进度看 overview 轮询）"""
    background_tasks.add_task(_bg_run_incremental)
    return ok({"message": "增量索引已提交后台执行"})


@router.post("/rebuild")
async def rebuild(
    request: RebuildRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(require_admin),
):
    """全量重建索引（切换向量模型/维度后必须执行）"""
    market = request.market.upper() if request.market else None
    if market and market not in ("CN", "HK", "US"):
        raise HTTPException(status_code=422, detail="market 必须是 CN/HK/US")
    background_tasks.add_task(_bg_rebuild, market)
    return ok({"message": f"知识库重建已提交后台执行（market={market or 'ALL'}）"})


@router.get("/citations")
async def get_citations(
    task_id: Optional[str] = Query(None),
    agent_key: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    current_user: dict = Depends(get_current_user),
):
    """引用校验计数（记分卡「引用有效率」数据源，按 task/agent 过滤）"""
    import asyncio

    return ok({
        "records": await asyncio.to_thread(
            knowledge_service.query_citations,
            task_id, agent_key, limit,
        )
    })


async def _bg_run_incremental():
    try:
        summary = await knowledge_service.run_index_now()
        logger.info(f"知识库手动增量索引完成: {summary}")
    except Exception as e:
        logger.error(f"知识库手动增量索引失败: {e}", exc_info=True)


async def _bg_rebuild(market: Optional[str]):
    try:
        summary = await knowledge_service.rebuild(market)
        logger.info(f"知识库重建完成: {summary}")
    except Exception as e:
        logger.error(f"知识库重建失败: {e}", exc_info=True)
