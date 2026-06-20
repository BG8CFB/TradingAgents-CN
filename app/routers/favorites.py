"""
自选股管理API路由
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, model_validator
import logging

from app.routers.auth_db import get_current_user
from app.services.favorites_service import favorites_service
from app.core.response import ok, safe_error_message

logger = logging.getLogger("webapi")

router = APIRouter(prefix="/api/favorites", tags=["Favorites"])


class AddFavoriteRequest(BaseModel):
    """添加自选股请求。

    symbol 是主字段（6 位代码），stock_code 为兼容字段。
    至少二选一；同时提供时以 symbol 为准。
    """
    symbol: Optional[str] = None
    stock_code: Optional[str] = None  # 兼容旧前端
    stock_name: str
    market: str = "A股"
    tags: List[str] = []
    notes: str = ""
    alert_price_high: Optional[float] = None
    alert_price_low: Optional[float] = None

    @model_validator(mode="after")
    def _resolve_code(self):
        if not (self.symbol or self.stock_code):
            raise ValueError("symbol 或 stock_code 至少需要提供一个")
        # 统一回填 stock_code 供下游 service 使用
        if not self.stock_code:
            self.stock_code = self.symbol
        if not self.symbol:
            self.symbol = self.stock_code
        return self


class UpdateFavoriteRequest(BaseModel):
    """更新自选股请求"""
    tags: Optional[List[str]] = None
    notes: Optional[str] = None
    alert_price_high: Optional[float] = None
    alert_price_low: Optional[float] = None


class FavoriteStockResponse(BaseModel):
    """自选股响应"""
    stock_code: str
    stock_name: str
    market: str
    added_at: str
    tags: List[str]
    notes: str
    alert_price_high: Optional[float]
    alert_price_low: Optional[float]
    # 实时数据
    current_price: Optional[float] = None
    change_percent: Optional[float] = None
    volume: Optional[int] = None


@router.get("/", response_model=dict)
async def get_favorites(
    current_user: dict = Depends(get_current_user)
):
    """获取用户自选股列表"""
    try:
        favorites = await favorites_service.get_user_favorites(current_user["id"])
        return ok(favorites)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=safe_error_message(e, "获取自选股失败")
        )


@router.post("/", response_model=dict)
async def add_favorite(
    request: AddFavoriteRequest,
    current_user: dict = Depends(get_current_user)
):
    """添加股票到自选股"""
    try:
        logger.info(f"📝 添加自选股请求: user_id={current_user['id']}, stock_code={request.stock_code}, stock_name={request.stock_name}")

        # 检查是否已存在
        is_fav = await favorites_service.is_favorite(current_user["id"], request.stock_code)
        logger.info(f"🔍 检查是否已存在: {is_fav}")

        if is_fav:
            logger.warning(f"⚠️ 股票已在自选股中: {request.stock_code}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="该股票已在自选股中"
            )

        # 添加到自选股
        logger.info("➕ 开始添加自选股...")
        success = await favorites_service.add_favorite(
            user_id=current_user["id"],
            stock_code=request.stock_code,
            stock_name=request.stock_name,
            market=request.market,
            tags=request.tags,
            notes=request.notes,
            alert_price_high=request.alert_price_high,
            alert_price_low=request.alert_price_low
        )

        logger.info(f"✅ 添加结果: success={success}")

        if success:
            return ok({"stock_code": request.stock_code}, "添加成功")
        else:
            logger.error("❌ 添加失败: success=False")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="添加失败"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 添加自选股异常: {type(e).__name__}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=safe_error_message(e, "添加自选股失败")
        )


@router.put("/{stock_code}", response_model=dict)
async def update_favorite(
    stock_code: str,
    request: UpdateFavoriteRequest,
    current_user: dict = Depends(get_current_user)
):
    """更新自选股信息"""
    try:
        success = await favorites_service.update_favorite(
            user_id=current_user["id"],
            stock_code=stock_code,
            tags=request.tags,
            notes=request.notes,
            alert_price_high=request.alert_price_high,
            alert_price_low=request.alert_price_low
        )

        if success:
            return ok({"stock_code": stock_code}, "更新成功")
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="自选股不存在"
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=safe_error_message(e, "更新自选股失败")
        )


@router.delete("/{stock_code}", response_model=dict)
async def remove_favorite(
    stock_code: str,
    current_user: dict = Depends(get_current_user)
):
    """从自选股中移除股票"""
    try:
        success = await favorites_service.remove_favorite(current_user["id"], stock_code)

        if success:
            return ok({"stock_code": stock_code}, "移除成功")
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="自选股不存在"
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=safe_error_message(e, "移除自选股失败")
        )


@router.get("/tags", response_model=dict)
async def get_user_tags(
    current_user: dict = Depends(get_current_user)
):
    """获取用户使用的所有标签"""
    try:
        tags = await favorites_service.get_user_tags(current_user["id"])
        return ok(tags)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=safe_error_message(e, "获取标签失败")
        )


@router.get("/check/{stock_code}", response_model=dict)
async def check_favorite(
    stock_code: str,
    current_user: dict = Depends(get_current_user)
):
    """检查股票是否在自选股中"""
    try:
        is_favorite = await favorites_service.is_favorite(current_user["id"], stock_code)
        return ok({"stock_code": stock_code, "is_favorite": is_favorite})
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=safe_error_message(e, "检查自选股状态失败")
        )


class SyncFavoritesRequest(BaseModel):
    """同步自选股实时行情请求"""
    data_source: str = "tushare"  # tushare/akshare


@router.post("/sync-realtime", response_model=dict)
async def sync_favorites_realtime(
    request: SyncFavoritesRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    同步自选股实时行情

    - **data_source**: 数据源（tushare/akshare）
    """
    try:
        logger.info(f"📊 开始同步自选股实时行情: user_id={current_user['id']}, data_source={request.data_source}")

        # 获取用户自选股列表
        favorites = await favorites_service.get_user_favorites(current_user["id"])

        if not favorites:
            logger.info("⚠️ 用户没有自选股")
            return ok({
                "total": 0,
                "success_count": 0,
                "failed_count": 0,
                "message": "没有自选股需要同步"
            })

        # 提取股票代码列表
        symbols = [fav.get("stock_code") or fav.get("symbol") for fav in favorites]
        symbols = [s for s in symbols if s]  # 过滤空值

        logger.info(f"🎯 需要同步的股票: {len(symbols)} 只 - {symbols}")

        # 通过 DataInterface 刷新实时行情
        from app.data.core.interface import DataInterface
        di = DataInterface.get_instance()

        logger.info("🔄 通过 DataInterface 刷新实时行情...")
        success_count = 0
        failed_count = 0
        data_source = "data_interface"

        for symbol in symbols:
            try:
                result = await di.refresh("CN", symbol, domains=["market_quotes"], force=True)
                if result.status in ("refreshed", "fresh", "success"):
                    success_count += 1
                else:
                    failed_count += 1
            except Exception as e:
                logger.debug(f"自选股行情同步失败 {symbol}: {e}")
                failed_count += 1

        logger.info(f"✅ 自选股实时行情同步完成: 同步 {success_count} 条记录")

        return ok({
            "total": len(symbols),
            "success_count": success_count,
            "failed_count": failed_count,
            "symbols": symbols,
            "data_source": data_source,
            "message": f"同步完成: {success_count} 条记录，来源 {data_source}"
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 同步自选股实时行情失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=safe_error_message(e, "同步失败")
        )
