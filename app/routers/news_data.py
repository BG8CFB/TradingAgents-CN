"""
新闻数据API路由
提供新闻数据查询、同步和管理接口
"""
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends, Query, status
from typing import Optional, List
from datetime import timedelta
from pydantic import BaseModel, Field
import logging

from app.routers.auth_db import get_current_user, require_admin
from app.core.response import ok, safe_error_message
from app.services.news_data_service import get_news_data_service, NewsQueryParams
from app.utils.timezone import now_utc

router = APIRouter(prefix="/api/news", tags=["News"])
logger = logging.getLogger("webapi")


class NewsSyncRequest(BaseModel):
    """新闻同步请求"""
    symbol: Optional[str] = Field(None, description="股票代码，为空则同步市场新闻")
    data_sources: Optional[List[str]] = Field(None, description="数据源列表")
    hours_back: int = Field(24, description="回溯小时数")
    max_news_per_source: int = Field(50, description="每个数据源最大新闻数量")


@router.get("/query/{symbol}", response_model=dict)
async def query_stock_news(
    symbol: str,
    hours_back: int = Query(24, description="回溯小时数"),
    limit: int = Query(20, description="返回数量限制"),
    category: Optional[str] = Query(None, description="新闻类别"),
    sentiment: Optional[str] = Query(None, description="情绪分析"),
    current_user: dict = Depends(get_current_user)
):
    """
    查询股票新闻（智能获取：优先数据库，无数据时实时获取）

    Args:
        symbol: 股票代码
        hours_back: 回溯小时数
        limit: 返回数量限制
        category: 新闻类别过滤
        sentiment: 情绪分析过滤

    Returns:
        dict: 新闻数据列表
    """
    try:
        service = await get_news_data_service()

        # 构建查询参数
        start_time = now_utc() - timedelta(hours=hours_back)

        params = NewsQueryParams(
            symbol=symbol,
            start_time=start_time,
            category=category,
            sentiment=sentiment,
            limit=limit,
            sort_by="publish_time",
            sort_order=-1
        )

        # 1. 先从数据库查询
        news_list = await service.query_news(params)
        data_source = "database"

        # 2. 如果数据库没有数据，实时获取
        if not news_list:
            logger.info(f"📰 数据库无新闻数据，通过 DataInterface 刷新: {symbol}")
            try:
                from app.data.core.interface import DataInterface
                di = DataInterface.get_instance()
                await di.refresh("CN", symbol, domains=["news"], force=True)

                # 重新查询
                news_list = await service.query_news(params)
                data_source = "realtime"

                if news_list:
                    logger.info(f"✅ 实时获取并保存 {len(news_list)} 条新闻")
                else:
                    logger.warning(f"⚠️ 实时获取新闻失败: {symbol}")

            except Exception as e:
                logger.error(f"❌ 实时获取新闻异常: {e}")

        return ok(data={
                "symbol": symbol,
                "hours_back": hours_back,
                "total_count": len(news_list),
                "news": news_list,
                "data_source": data_source
            },
            message=f"查询成功，返回 {len(news_list)} 条新闻（来源：{data_source}）"
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=safe_error_message(e, "查询股票新闻失败")
        )


@router.get("/latest", response_model=dict)
async def get_latest_news(
    symbol: Optional[str] = Query(None, description="股票代码，为空则获取所有新闻"),
    limit: int = Query(10, description="返回数量限制"),
    hours_back: int = Query(24, description="回溯小时数"),
    current_user: dict = Depends(get_current_user)
):
    """
    获取最新新闻
    
    Args:
        symbol: 股票代码，为空则获取所有新闻
        limit: 返回数量限制
        hours_back: 回溯小时数
        
    Returns:
        dict: 最新新闻列表
    """
    try:
        service = await get_news_data_service()
        
        # 获取最新新闻
        news_list = await service.get_latest_news(
            symbol=symbol,
            limit=limit,
            hours_back=hours_back
        )
        
        return ok(data={
                "symbol": symbol,
                "limit": limit,
                "hours_back": hours_back,
                "total_count": len(news_list),
                "news": news_list
            },
            message=f"获取最新新闻成功，返回 {len(news_list)} 条"
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=safe_error_message(e, "获取最新新闻失败")
        )


@router.post("/sync/start", response_model=dict)
async def start_news_sync(
    request: NewsSyncRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(require_admin)
):
    """启动新闻同步任务。"""
    try:
        from app.data.core.interface import DataInterface

        DataInterface.get_instance()

        if request.symbol:
            background_tasks.add_task(
                _execute_news_refresh, request.symbol
            )
            message = f"股票 {request.symbol} 新闻同步任务已启动"
        else:
            background_tasks.add_task(
                _execute_news_refresh, None
            )
            message = "市场新闻同步任务已启动"

        return ok(data={
                "sync_type": "stock" if request.symbol else "market",
                "symbol": request.symbol,
                "data_sources": request.data_sources,
                "hours_back": request.hours_back,
                "max_news_per_source": request.max_news_per_source
            },
            message=message
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=safe_error_message(e, "启动新闻同步失败")
        )


async def _execute_news_refresh(symbol: Optional[str]):
    """后台新闻刷新。"""
    try:
        from app.data.core.interface import DataInterface
        di = DataInterface.get_instance()
        if symbol:
            await di.refresh("CN", symbol, domains=["news"], force=True)
        else:
            from app.worker.scheduler_setup import get_scheduler_engine
            engine = get_scheduler_engine()
            if engine:
                engine.trigger_job("cn", "news")
    except Exception as e:
        logger.error(f"❌ 后台新闻刷新失败: {e}")
