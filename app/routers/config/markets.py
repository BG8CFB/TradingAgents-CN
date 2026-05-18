"""
配置管理 - 市场分类 & 模型目录子路由

包含：
- 市场分类 CRUD（GET/POST/PUT/DELETE /market-categories）
- 可用模型列表（GET /models）
- 模型目录 CRUD（GET/POST/DELETE /model-catalog, POST /model-catalog/init）
"""

import logging
from typing import List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.routers.auth_db import get_current_user, require_admin
from app.models.user import User
from app.models.config import (
    MarketCategory,
    MarketCategoryRequest,
    ModelCatalog,
    ModelInfo,
)
from app.services.config_service import config_service
from app.services.operation_log_service import log_operation
from app.models.operation_log import ActionType

logger = logging.getLogger("webapi")

router = APIRouter(tags=["Config"])


# ==================== 市场分类管理 ====================

@router.get("/market-categories", response_model=List[MarketCategory])
async def get_market_categories(
    current_user: User = Depends(get_current_user)
):
    """获取所有市场分类"""
    try:
        categories = await config_service.get_market_categories()
        return categories
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取市场分类失败: {str(e)}"
        )


@router.post("/market-categories", response_model=dict)
async def add_market_category(
    request: MarketCategoryRequest,
    current_user: User = Depends(require_admin)
):
    """添加市场分类"""
    try:
        category = MarketCategory(**request.model_dump())
        success = await config_service.add_market_category(category)

        if success:
            # 审计日志（忽略异常）
            try:
                await log_operation(
                    user_id=str(current_user.get("id", "")),
                    username=current_user.get("username", "unknown"),
                    action_type=ActionType.CONFIG_MANAGEMENT,
                    action="add_market_category",
                    details={"id": str(getattr(category, 'id', ''))},
                    success=True,
                )
            except Exception:
                pass
            return {"message": "市场分类添加成功", "id": category.id}
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="市场分类ID已存在"
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"添加市场分类失败: {str(e)}"
        )


@router.put("/market-categories/{category_id}", response_model=dict)
async def update_market_category(
    category_id: str,
    request: Dict[str, Any],
    current_user: User = Depends(require_admin)
):
    """更新市场分类"""
    try:
        success = await config_service.update_market_category(category_id, request)

        if success:
            # 审计日志（忽略异常）
            try:
                await log_operation(
                    user_id=str(current_user.get("id", "")),
                    username=current_user.get("username", "unknown"),
                    action_type=ActionType.CONFIG_MANAGEMENT,
                    action="update_market_category",
                    details={"category_id": category_id, "changed_keys": list(request.keys())},
                    success=True,
                )
            except Exception:
                pass
            return {"message": "市场分类更新成功"}
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="市场分类不存在"
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新市场分类失败: {str(e)}"
        )


@router.delete("/market-categories/{category_id}", response_model=dict)
async def delete_market_category(
    category_id: str,
    current_user: User = Depends(require_admin)
):
    """删除市场分类"""
    try:
        success = await config_service.delete_market_category(category_id)

        if success:
            # 审计日志（忽略异常）
            try:
                await log_operation(
                    user_id=str(current_user.get("id", "")),
                    username=current_user.get("username", "unknown"),
                    action_type=ActionType.CONFIG_MANAGEMENT,
                    action="delete_market_category",
                    details={"category_id": category_id},
                    success=True,
                )
            except Exception:
                pass
            return {"message": "市场分类删除成功"}
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="无法删除分类，可能还有数据源使用此分类"
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"删除市场分类失败: {str(e)}"
        )


# ==================== 可用模型列表 ====================

@router.get("/models", response_model=List[Dict[str, Any]])
async def get_available_models(
    current_user: User = Depends(require_admin)
):
    """获取可用的模型列表"""
    try:
        models = await config_service.get_available_models()
        return models
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取模型列表失败: {str(e)}"
        )


# ==================== 模型目录管理 ====================

class ModelCatalogRequest(BaseModel):
    """模型目录请求"""
    provider: str
    provider_name: str
    models: List[Dict[str, Any]]


@router.get("/model-catalog", response_model=List[Dict[str, Any]])
async def get_model_catalog(
    current_user: User = Depends(require_admin)
):
    """获取所有模型目录"""
    try:
        catalogs = await config_service.get_model_catalog()
        return [catalog.model_dump(by_alias=False) for catalog in catalogs]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取模型目录失败: {str(e)}"
        )


@router.get("/model-catalog/{provider}", response_model=Dict[str, Any])
async def get_provider_model_catalog(
    provider: str,
    current_user: User = Depends(require_admin)
):
    """获取指定厂家的模型目录"""
    try:
        catalog = await config_service.get_provider_models(provider)
        if not catalog:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"未找到厂家 {provider} 的模型目录"
            )
        return catalog.model_dump(by_alias=False)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取模型目录失败: {str(e)}"
        )


@router.post("/model-catalog", response_model=dict)
async def save_model_catalog(
    request: ModelCatalogRequest,
    current_user: User = Depends(require_admin)
):
    """保存或更新模型目录"""
    try:
        logger.info(f"收到保存模型目录请求: provider={request.provider}, models数量={len(request.models)}")
        logger.info(f"请求数据: {request.model_dump()}")

        # 转换为 ModelInfo 列表
        models = [ModelInfo(**m) for m in request.models]
        logger.info(f"成功转换 {len(models)} 个模型")

        catalog = ModelCatalog(
            provider=request.provider,
            provider_name=request.provider_name,
            models=models
        )
        logger.info(f"创建 ModelCatalog 对象成功")

        success = await config_service.save_model_catalog(catalog)
        logger.info(f"保存结果: {success}")

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="保存模型目录失败"
            )

        # 记录操作日志
        await log_operation(
            user_id=str(current_user["id"]),
            username=current_user.get("username", "unknown"),
            action_type=ActionType.CONFIG_MANAGEMENT,
            action="update_model_catalog",
            details={"provider": request.provider, "provider_name": request.provider_name, "models_count": len(request.models)}
        )

        return {"success": True, "message": "模型目录保存成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"保存模型目录失败: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"保存模型目录失败: {str(e)}"
        )


@router.delete("/model-catalog/{provider}", response_model=dict)
async def delete_model_catalog(
    provider: str,
    current_user: User = Depends(require_admin)
):
    """删除模型目录"""
    try:
        success = await config_service.delete_model_catalog(provider)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"未找到厂家 {provider} 的模型目录"
            )

        # 记录操作日志
        await log_operation(
            user_id=str(current_user["id"]),
            username=current_user.get("username", "unknown"),
            action_type=ActionType.CONFIG_MANAGEMENT,
            action="delete_model_catalog",
            details={"provider": provider}
        )

        return {"success": True, "message": "模型目录删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"删除模型目录失败: {str(e)}"
        )


@router.post("/model-catalog/init", response_model=dict)
async def init_model_catalog(
    current_user: User = Depends(require_admin)
):
    """初始化默认模型目录"""
    try:
        success = await config_service.init_default_model_catalog()
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="初始化模型目录失败"
            )

        return {"success": True, "message": "模型目录初始化成功"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"初始化模型目录失败: {str(e)}"
        )
