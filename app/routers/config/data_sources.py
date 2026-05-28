"""
配置管理 - 数据源子路由

包含：
- 数据源配置 CRUD（GET/POST/PUT/DELETE /datasource）
- 数据源分组管理（GET/POST/PUT/DELETE /datasource-groupings）
- 分类数据源排序（PUT /market-categories/{category_id}/datasource-order）
- 设置默认数据源（POST /datasource/set-default）
"""

import logging
from typing import List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.routers.auth_db import get_current_user, require_admin
from app.models.user import User
from app.models.config import (
    DataSourceConfigRequest,
    DataSourceConfig,
    DataSourceGrouping,
    DataSourceGroupingRequest,
    DataSourceOrderRequest,
)
from app.services.config_service import config_service
from app.services.operation_log_service import log_operation
from app.models.operation_log import ActionType
from app.routers.config.llm import SetDefaultRequest

logger = logging.getLogger("webapi")

router = APIRouter(tags=["Config"])


# ===== 共享辅助函数 =====

def _sanitize_datasource_configs(items):
    """
    脱敏数据源配置，返回缩略的 API Key
    API Key 仅从数据库读取。
    """
    try:
        from app.utils.api_key_utils import truncate_api_key

        result = []
        for item in items:
            data = item.model_dump()

            # 处理 API Key - 仅从数据库读取
            db_key = data.get("api_key")
            if db_key:
                data["api_key"] = truncate_api_key(db_key)
            else:
                data["api_key"] = None

            # 处理 API Secret - 为了支持本地AI模型，不再验证有效性
            db_secret = data.get("api_secret")
            if db_secret:
                data["api_secret"] = truncate_api_key(db_secret)
            else:
                data["api_secret"] = None

            result.append(DataSourceConfig(**data))

        return result
    except Exception as e:
        logger.warning(f"脱敏数据源配置失败: {e}")
        return items


# ==================== 数据源配置管理 ====================

@router.get("/datasource", response_model=List[DataSourceConfig])
async def get_data_source_configs(
    current_user: User = Depends(get_current_user)
):
    """获取所有数据源配置"""
    try:
        config = await config_service.get_system_config()
        if not config:
            return []
        return _sanitize_datasource_configs(config.data_source_configs)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取数据源配置失败: {str(e)}"
        )


@router.post("/datasource", response_model=dict)
async def add_data_source_config(
    request: DataSourceConfigRequest,
    current_user: User = Depends(require_admin)
):
    """添加数据源配置"""
    try:
        # 开源版本：所有用户都可以修改配置

        # 获取当前配置
        config = await config_service.get_system_config()
        if not config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="系统配置不存在"
            )

        # 添加新的数据源配置
        # 支持保存 API Key（与大模型厂家管理逻辑一致）

        _req = request.model_dump()

        # 处理 API Key - 为了支持本地AI模型，不再验证
        if 'api_key' in _req:
            api_key = _req.get('api_key', '')
            # 为了支持本地AI模型，保留用户输入的任何值
            _req['api_key'] = api_key

        # 处理 API Secret - 为了支持本地AI模型，不再验证
        if 'api_secret' in _req:
            api_secret = _req.get('api_secret', '')
            # 为了支持本地AI模型，保留用户输入的任何值
            _req['api_secret'] = api_secret

        ds_config = DataSourceConfig(**_req)
        config.data_source_configs.append(ds_config)

        success = await config_service.save_system_config(config)
        if success:
            # 自动创建数据源分组关系
            market_categories = _req.get('market_categories', [])
            if market_categories:
                for category_id in market_categories:
                    try:
                        grouping = DataSourceGrouping(
                            data_source_name=ds_config.name,
                            market_category_id=category_id,
                            priority=ds_config.priority,
                            enabled=ds_config.enabled
                        )
                        await config_service.add_datasource_to_category(grouping)
                    except Exception as e:
                        # 如果分组已存在或其他错误，记录但不影响主流程
                        logger.warning(f"自动创建数据源分组失败: {str(e)}")

            # 审计日志（忽略异常）
            try:
                await log_operation(
                    user_id=str(current_user.get("id", "")),
                    username=current_user.get("username", "unknown"),
                    action_type=ActionType.CONFIG_MANAGEMENT,
                    action="add_data_source_config",
                    details={"name": ds_config.name, "market_categories": market_categories},
                    success=True,
                )
            except Exception as e:
                logger.debug(f"记录操作日志失败: {e}")
                pass
            return {"message": "数据源配置添加成功", "name": ds_config.name}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="数据源配置添加失败"
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"添加数据源配置失败: {str(e)}"
        )


@router.put("/datasource/{name}", response_model=dict)
async def update_data_source_config(
    name: str,
    request: DataSourceConfigRequest,
    current_user: User = Depends(require_admin)
):
    """更新数据源配置"""
    try:
        # 获取当前配置
        config = await config_service.get_system_config()
        if not config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="系统配置不存在"
            )

        # 查找并更新数据源配置

        def _truncate_api_key(api_key: str, prefix_len: int = 6, suffix_len: int = 6) -> str:
            """截断 API Key 用于显示"""
            if not api_key or len(api_key) <= prefix_len + suffix_len:
                return api_key
            return f"{api_key[:prefix_len]}...{api_key[-suffix_len:]}"

        for i, ds_config in enumerate(config.data_source_configs):
            if ds_config.name == name:
                # 更新配置
                # 处理 API Key 的更新逻辑（与大模型厂家管理逻辑一致）
                _req = request.model_dump()

                # 处理 API Key - 为了支持本地AI模型，简化验证逻辑
                if 'api_key' in _req:
                    api_key = _req.get('api_key')
                    logger.info(f"[API Key 更新] 收到的 API Key: (长度: {len(api_key) if api_key else 0})")

                    # 为了支持本地AI模型，直接使用用户输入的值
                    _req['api_key'] = api_key if api_key is not None else ds_config.api_key

                # 处理 API Secret - 为了支持本地AI模型，简化验证逻辑
                if 'api_secret' in _req:
                    api_secret = _req.get('api_secret')
                    logger.info(f"[API Secret 更新] 收到的 API Secret: (长度: {len(api_secret) if api_secret else 0})")

                    # 为了支持本地AI模型，直接使用用户输入的值
                    _req['api_secret'] = api_secret if api_secret is not None else ds_config.api_secret

                updated_config = DataSourceConfig(**_req)
                config.data_source_configs[i] = updated_config

                success = await config_service.save_system_config(config)
                if success:
                    # 同步市场分类关系
                    new_categories = set(_req.get('market_categories', []))

                    # 获取当前的分组关系
                    current_groupings = await config_service.get_datasource_groupings()
                    current_categories = set(
                        g.market_category_id
                        for g in current_groupings
                        if g.data_source_name == name
                    )

                    # 需要添加的分类
                    to_add = new_categories - current_categories
                    for category_id in to_add:
                        try:
                            grouping = DataSourceGrouping(
                                data_source_name=name,
                                market_category_id=category_id,
                                priority=updated_config.priority,
                                enabled=updated_config.enabled
                            )
                            await config_service.add_datasource_to_category(grouping)
                        except Exception as e:
                            logger.warning(f"添加数据源分组失败: {str(e)}")

                    # 需要删除的分类
                    to_remove = current_categories - new_categories
                    for category_id in to_remove:
                        try:
                            await config_service.remove_datasource_from_category(name, category_id)
                        except Exception as e:
                            logger.warning(f"删除数据源分组失败: {str(e)}")

                    # 审计日志（忽略异常）
                    try:
                        await log_operation(
                            user_id=str(current_user.get("id", "")),
                            username=current_user.get("username", "unknown"),
                            action_type=ActionType.CONFIG_MANAGEMENT,
                            action="update_data_source_config",
                            details={"name": name, "market_categories": list(new_categories)},
                            success=True,
                        )
                    except Exception as e:
                        logger.debug(f"记录操作日志失败: {e}")
                        pass
                    return {"message": "数据源配置更新成功"}
                else:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="数据源配置更新失败"
                    )

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据源配置不存在"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新数据源配置失败: {str(e)}"
        )


@router.delete("/datasource/{name}", response_model=dict)
async def delete_data_source_config(
    name: str,
    current_user: User = Depends(require_admin)
):
    """删除数据源配置"""
    try:
        # 获取当前配置
        config = await config_service.get_system_config()
        if not config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="系统配置不存在"
            )

        # 查找并删除数据源配置
        for i, ds_config in enumerate(config.data_source_configs):
            if ds_config.name == name:
                config.data_source_configs.pop(i)

                success = await config_service.save_system_config(config)
                if success:
                    # 审计日志（忽略异常）
                    try:
                        await log_operation(
                            user_id=str(current_user.get("id", "")),
                            username=current_user.get("username", "unknown"),
                            action_type=ActionType.CONFIG_MANAGEMENT,
                            action="delete_data_source_config",
                            details={"name": name},
                            success=True,
                        )
                    except Exception as e:
                        logger.debug(f"记录操作日志失败: {e}")
                        pass
                    return {"message": "数据源配置删除成功"}
                else:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="数据源配置删除失败"
                    )

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据源配置不存在"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"删除数据源配置失败: {str(e)}"
        )


@router.post("/datasource/set-default")
async def set_default_data_source(
    request: SetDefaultRequest,
    current_user: User = Depends(require_admin)
):
    """设置默认数据源"""
    try:
        success = await config_service.set_default_data_source(request.name)
        if success:
            # 审计日志（忽略异常）
            try:
                await log_operation(
                    user_id=str(current_user.get("id", "")),
                    username=current_user.get("username", "unknown"),
                    action_type=ActionType.CONFIG_MANAGEMENT,
                    action="set_default_datasource",
                    details={"name": request.name},
                    success=True,
                )
            except Exception as e:
                logger.debug(f"记录操作日志失败: {e}")
                pass
            return {"message": "默认数据源设置成功", "default_data_source": request.name}
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="指定的数据源不存在"
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"设置默认数据源失败: {str(e)}"
        )


# ==================== 数据源分组管理 ====================

@router.get("/datasource-groupings", response_model=List[DataSourceGrouping])
async def get_datasource_groupings(
    current_user: User = Depends(require_admin)
):
    """获取所有数据源分组关系"""
    try:
        groupings = await config_service.get_datasource_groupings()
        return groupings
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取数据源分组关系失败: {str(e)}"
        )


@router.post("/datasource-groupings", response_model=dict)
async def add_datasource_to_category(
    request: DataSourceGroupingRequest,
    current_user: User = Depends(require_admin)
):
    """将数据源添加到分类"""
    try:
        grouping = DataSourceGrouping(**request.model_dump())
        success = await config_service.add_datasource_to_category(grouping)

        if success:
            # 审计日志（忽略异常）
            try:
                await log_operation(
                    user_id=str(current_user.get("id", "")),
                    username=current_user.get("username", "unknown"),
                    action_type=ActionType.CONFIG_MANAGEMENT,
                    action="add_datasource_to_category",
                    details={"data_source_name": request.data_source_name, "category_id": request.category_id},
                    success=True,
                )
            except Exception as e:
                logger.debug(f"记录操作日志失败: {e}")
                pass
            return {"message": "数据源添加到分类成功"}
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="数据源已在该分类中"
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"添加数据源到分类失败: {str(e)}"
        )


@router.delete("/datasource-groupings/{data_source_name}/{category_id}", response_model=dict)
async def remove_datasource_from_category(
    data_source_name: str,
    category_id: str,
    current_user: User = Depends(require_admin)
):
    """从分类中移除数据源"""
    try:
        success = await config_service.remove_datasource_from_category(data_source_name, category_id)

        if success:
            # 审计日志（忽略异常）
            try:
                await log_operation(
                    user_id=str(current_user.get("id", "")),
                    username=current_user.get("username", "unknown"),
                    action_type=ActionType.CONFIG_MANAGEMENT,
                    action="remove_datasource_from_category",
                    details={"data_source_name": data_source_name, "category_id": category_id},
                    success=True,
                )
            except Exception as e:
                logger.debug(f"记录操作日志失败: {e}")
                pass
            return {"message": "数据源从分类中移除成功"}
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="数据源分组关系不存在"
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"从分类中移除数据源失败: {str(e)}"
        )


@router.put("/datasource-groupings/{data_source_name}/{category_id}", response_model=dict)
async def update_datasource_grouping(
    data_source_name: str,
    category_id: str,
    request: Dict[str, Any],
    current_user: User = Depends(require_admin)
):
    """更新数据源分组关系"""
    try:
        success = await config_service.update_datasource_grouping(data_source_name, category_id, request)

        if success:
            # 审计日志（忽略异常）
            try:
                await log_operation(
                    user_id=str(current_user.get("id", "")),
                    username=current_user.get("username", "unknown"),
                    action_type=ActionType.CONFIG_MANAGEMENT,
                    action="update_datasource_grouping",
                    details={"data_source_name": data_source_name, "category_id": category_id, "changed_keys": list(request.keys())},
                    success=True,
                )
            except Exception as e:
                logger.debug(f"记录操作日志失败: {e}")
                pass
            return {"message": "数据源分组关系更新成功"}
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="数据源分组关系不存在"
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新数据源分组关系失败: {str(e)}"
        )


@router.put("/market-categories/{category_id}/datasource-order", response_model=dict)
async def update_category_datasource_order(
    category_id: str,
    request: DataSourceOrderRequest,
    current_user: User = Depends(require_admin)
):
    """更新分类中数据源的排序"""
    try:
        success = await config_service.update_category_datasource_order(category_id, request.data_sources)

        if success:
            # 审计日志（忽略异常）
            try:
                await log_operation(
                    user_id=str(current_user.get("id", "")),
                    username=current_user.get("username", "unknown"),
                    action_type=ActionType.CONFIG_MANAGEMENT,
                    action="update_category_datasource_order",
                    details={"category_id": category_id, "data_sources": request.data_sources},
                    success=True,
                )
            except Exception as e:
                logger.debug(f"记录操作日志失败: {e}")
                pass
            return {"message": "数据源排序更新成功"}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="数据源排序更新失败"
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新数据源排序失败: {str(e)}"
        )
