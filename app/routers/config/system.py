"""
配置管理 - 系统配置子路由

包含：
- 系统配置获取（GET /system）
- 配置重载（POST /reload）
- 系统设置 CRUD（GET/PUT /settings, GET /settings/meta）
- 配置导出/导入（POST /export, POST /import）
- 传统配置迁移（POST /migrate-legacy）
- 数据库配置 CRUD（GET/POST/PUT/DELETE /database）
- 配置连接测试（POST /test, POST /database/{db_name}/test）
"""

import logging
from typing import List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.routers.auth_db import get_current_user
from app.models.user import User
from app.models.config import (
    SystemConfigResponse,
    DatabaseConfigRequest,
    ConfigTestRequest,
    ConfigTestResponse,
    DatabaseConfig,
)
from app.services.config_service import config_service
from app.utils.timezone import now_tz
from app.services.operation_log_service import log_operation
from app.models.operation_log import ActionType
from app.services.config_provider import provider as config_provider

logger = logging.getLogger("webapi")

router = APIRouter(tags=["Config"])


# ===== 共享辅助函数 =====

def _sanitize_llm_configs(items):
    """脱敏 LLM 配置中的 API Key"""
    try:
        from app.models.config import LLMConfig
        return [LLMConfig(**{**i.model_dump(), "api_key": None}) for i in items]
    except Exception:
        return items


def _sanitize_datasource_configs(items):
    """脱敏数据源配置"""
    try:
        from app.utils.api_key_utils import truncate_api_key, get_env_api_key_for_datasource
        from app.models.config import DataSourceConfig

        result = []
        for item in items:
            data = item.model_dump()
            db_key = data.get("api_key")
            if db_key:
                data["api_key"] = truncate_api_key(db_key)
            else:
                ds_type = data.get("type")
                if isinstance(ds_type, str):
                    env_key = get_env_api_key_for_datasource(ds_type)
                    data["api_key"] = truncate_api_key(env_key) if env_key else None
                else:
                    data["api_key"] = None

            db_secret = data.get("api_secret")
            data["api_secret"] = truncate_api_key(db_secret) if db_secret else None

            result.append(DataSourceConfig(**data))
        return result
    except Exception as e:
        logger.warning(f"脱敏数据源配置失败: {e}")
        return items


def _sanitize_database_configs(items):
    """脱敏数据库配置中的密码"""
    try:
        return [DatabaseConfig(**{**i.model_dump(), "password": None}) for i in items]
    except Exception:
        return items


def _sanitize_kv(d: Dict[str, Any]) -> Dict[str, Any]:
    """对字典中的可能敏感键进行脱敏（仅用于响应）。"""
    try:
        if not isinstance(d, dict):
            return d
        sens_patterns = ("key", "secret", "password", "token", "client_secret")
        redacted = {}
        for k, v in d.items():
            if isinstance(k, str) and any(p in k.lower() for p in sens_patterns):
                redacted[k] = None
            else:
                redacted[k] = v
        return redacted
    except Exception:
        return d


# ===== 配置重载端点 =====

@router.post("/reload", summary="重新加载配置")
async def reload_config(current_user: dict = Depends(get_current_user)):
    """
    重新加载配置并桥接到环境变量

    用于配置更新后立即生效，无需重启服务
    """
    try:
        from app.core.config_bridge import reload_bridged_config

        success = await reload_bridged_config()

        if success:
            await log_operation(
                user_id=str(current_user.get("user_id", "")),
                username=current_user.get("username", "unknown"),
                action_type=ActionType.CONFIG_MANAGEMENT,
                action="重载配置",
                details={"action": "reload_config"},
                ip_address="",
                user_agent=""
            )

            return {
                "success": True,
                "message": "配置重载成功",
                "data": {
                    "reloaded_at": now_tz().isoformat()
                }
            }
        else:
            return {
                "success": False,
                "message": "配置重载失败，请查看日志"
            }
    except Exception as e:
        logger.error(f"配置重载失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"配置重载失败: {str(e)}"
        )


# ===== 系统配置获取 =====

@router.get("/system", response_model=SystemConfigResponse)
async def get_system_config(
    current_user: User = Depends(get_current_user)
):
    """获取系统配置"""
    try:
        config = await config_service.get_system_config()
        if not config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="系统配置不存在"
            )

        return SystemConfigResponse(
            config_name=config.config_name,
            config_type=config.config_type,
            llm_configs=_sanitize_llm_configs(config.llm_configs),
            default_llm=config.default_llm,
            data_source_configs=_sanitize_datasource_configs(config.data_source_configs),
            default_data_source=config.default_data_source,
            database_configs=_sanitize_database_configs(config.database_configs),
            system_settings=_sanitize_kv(config.system_settings),
            created_at=config.created_at,
            updated_at=config.updated_at,
            version=config.version,
            is_active=config.is_active
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取系统配置失败: {str(e)}"
        )


# ===== 系统设置 =====

@router.get("/settings", response_model=Dict[str, Any])
async def get_system_settings(
    current_user: User = Depends(get_current_user)
):
    """获取系统设置"""
    try:
        effective = await config_provider.get_effective_system_settings()
        return _sanitize_kv(effective)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取系统设置失败: {str(e)}"
        )


@router.get("/settings/meta", response_model=dict)
async def get_system_settings_meta(
    current_user: User = Depends(get_current_user)
):
    """获取系统设置的元数据（敏感性、可编辑性、来源、是否有值）。
    返回结构：{success, data: {items: [{key,sensitive,editable,source,has_value}]}, message}
    """
    try:
        meta_map = await config_provider.get_system_settings_meta()
        items = [
            {"key": k, **v} for k, v in meta_map.items()
        ]
        return {"success": True, "data": {"items": items}, "message": ""}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取系统设置元数据失败: {str(e)}"
        )


@router.put("/settings", response_model=dict)
async def update_system_settings(
    settings: Dict[str, Any],
    current_user: User = Depends(get_current_user)
):
    """更新系统设置"""
    try:
        # 打印接收到的设置（用于调试）
        logger.info(f"接收到的系统设置更新请求，包含 {len(settings)} 项")
        if 'analyst_model' in settings:
            logger.info(f"  analyst_model: {settings['analyst_model']}")
        else:
            logger.warning(f"  未包含 analyst_model")
        if 'debate_model' in settings:
            logger.info(f"  debate_model: {settings['debate_model']}")
        else:
            logger.warning(f"  未包含 debate_model")

        success = await config_service.update_system_settings(settings)
        if success:
            # 审计日志（忽略日志异常，不影响主流程）
            try:
                await log_operation(
                    user_id=str(getattr(current_user, "id", "")),
                    username=getattr(current_user, "username", "unknown"),
                    action_type=ActionType.CONFIG_MANAGEMENT,
                    action="update_system_settings",
                    details={"changed_keys": list(settings.keys())},
                    success=True,
                )
            except Exception:
                pass
            # 失效缓存
            try:
                config_provider.invalidate()
            except Exception:
                pass
            return {"message": "系统设置更新成功"}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="系统设置更新失败"
            )
    except HTTPException:
        raise
    except Exception as e:
        # 审计失败记录（忽略日志异常）
        try:
            await log_operation(
                user_id=str(getattr(current_user, "id", "")),
                username=getattr(current_user, "username", "unknown"),
                action_type=ActionType.CONFIG_MANAGEMENT,
                action="update_system_settings",
                details={"changed_keys": list(settings.keys())},
                success=False,
                error_message=str(e),
            )
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新系统设置失败: {str(e)}"
        )


# ===== 配置导出/导入 =====

@router.post("/export", response_model=dict)
async def export_config(
    current_user: User = Depends(get_current_user)
):
    """导出配置"""
    try:
        config_data = await config_service.export_config()
        # 审计日志（忽略异常）
        try:
            await log_operation(
                user_id=str(getattr(current_user, "id", "")),
                username=getattr(current_user, "username", "unknown"),
                action_type=ActionType.DATA_EXPORT,
                action="export_config",
                details={"size": len(str(config_data))},
                success=True,
            )
        except Exception:
            pass
        return {
            "message": "配置导出成功",
            "data": config_data,
            "exported_at": now_tz().isoformat()
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"导出配置失败: {str(e)}"
        )


@router.post("/import", response_model=dict)
async def import_config(
    config_data: Dict[str, Any],
    current_user: User = Depends(get_current_user)
):
    """导入配置"""
    try:
        success = await config_service.import_config(config_data)
        if success:
            # 审计日志（忽略异常）
            try:
                await log_operation(
                    user_id=str(getattr(current_user, "id", "")),
                    username=getattr(current_user, "username", "unknown"),
                    action_type=ActionType.DATA_IMPORT,
                    action="import_config",
                    details={"keys": list(config_data.keys())[:10]},
                    success=True,
                )
            except Exception:
                pass
            return {"message": "配置导入成功"}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="配置导入失败"
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"导入配置失败: {str(e)}"
        )


@router.post("/migrate-legacy", response_model=dict)
async def migrate_legacy_config(
    current_user: User = Depends(get_current_user)
):
    """迁移传统配置"""
    try:
        success = await config_service.migrate_legacy_config()
        if success:
            # 审计日志（忽略异常）
            try:
                await log_operation(
                    user_id=str(getattr(current_user, "id", "")),
                    username=getattr(current_user, "username", "unknown"),
                    action_type=ActionType.CONFIG_MANAGEMENT,
                    action="migrate_legacy_config",
                    details={},
                    success=True,
                )
            except Exception:
                pass
            return {"message": "传统配置迁移成功"}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="传统配置迁移失败"
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"迁移传统配置失败: {str(e)}"
        )


# ===== 配置连接测试 =====

@router.post("/test", response_model=ConfigTestResponse)
async def test_config(
    request: ConfigTestRequest,
    current_user: User = Depends(get_current_user)
):
    """测试配置连接"""
    try:
        from app.models.config import LLMConfig, DataSourceConfig

        if request.config_type == "llm":
            llm_config = LLMConfig(**request.config_data)
            result = await config_service.test_llm_config(llm_config)
        elif request.config_type == "datasource":
            ds_config = DataSourceConfig(**request.config_data)
            result = await config_service.test_data_source_config(ds_config)
        elif request.config_type == "database":
            db_config = DatabaseConfig(**request.config_data)
            result = await config_service.test_database_config(db_config)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="不支持的配置类型"
            )

        return ConfigTestResponse(**result)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"测试配置失败: {str(e)}"
        )


@router.post("/database/{db_name}/test", response_model=ConfigTestResponse)
async def test_saved_database_config(
    db_name: str,
    current_user: dict = Depends(get_current_user)
):
    """测试已保存的数据库配置（从数据库中获取完整配置包括密码）"""
    try:
        logger.info(f"测试已保存的数据库配置: {db_name}")

        # 从数据库获取完整的系统配置
        config = await config_service.get_system_config()
        if not config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="系统配置不存在"
            )

        # 查找指定的数据库配置
        db_config = None
        for db in config.database_configs:
            if db.name == db_name:
                db_config = db
                break

        if not db_config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"数据库配置 '{db_name}' 不存在"
            )

        logger.info(f"找到数据库配置: {db_config.name} ({db_config.type})")
        logger.info(f"连接信息: {db_config.host}:{db_config.port}")
        logger.info(f"用户名: {db_config.username or '(无)'}")
        logger.info(f"密码: {'***' if db_config.password else '(无)'}")

        # 使用完整配置进行测试
        result = await config_service.test_database_config(db_config)

        return ConfigTestResponse(**result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"测试数据库配置失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"测试数据库配置失败: {str(e)}"
        )


# ===== 数据库配置管理端点 =====

@router.get("/database", response_model=List[DatabaseConfig])
async def get_database_configs(
    current_user: dict = Depends(get_current_user)
):
    """获取所有数据库配置"""
    try:
        logger.info("获取数据库配置列表...")
        configs = await config_service.get_database_configs()
        logger.info(f"获取到 {len(configs)} 个数据库配置")
        return _sanitize_database_configs(configs)
    except Exception as e:
        logger.error(f"获取数据库配置失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取数据库配置失败: {str(e)}"
        )


@router.get("/database/{db_name}", response_model=DatabaseConfig)
async def get_database_config(
    db_name: str,
    current_user: dict = Depends(get_current_user)
):
    """获取指定的数据库配置"""
    try:
        logger.info(f"获取数据库配置: {db_name}")
        config = await config_service.get_database_config(db_name)

        if not config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"数据库配置 '{db_name}' 不存在"
            )

        return _sanitize_database_configs([config])[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取数据库配置失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取数据库配置失败: {str(e)}"
        )


@router.post("/database", response_model=dict)
async def add_database_config(
    request: DatabaseConfigRequest,
    current_user: dict = Depends(get_current_user)
):
    """添加数据库配置"""
    try:
        logger.info(f"添加数据库配置: {request.name}")

        # 转换为 DatabaseConfig 对象
        db_config = DatabaseConfig(**request.model_dump())

        # 添加配置
        success = await config_service.add_database_config(db_config)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="添加数据库配置失败，可能已存在同名配置"
            )

        # 记录操作日志
        await log_operation(
            user_id=current_user["id"],
            username=current_user.get("username", "unknown"),
            action_type=ActionType.CONFIG_MANAGEMENT,
            action=f"添加数据库配置: {request.name}",
            details={"name": request.name, "type": request.type, "host": request.host, "port": request.port}
        )

        return {"success": True, "message": "数据库配置添加成功"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"添加数据库配置失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"添加数据库配置失败: {str(e)}"
        )


@router.put("/database/{db_name}", response_model=dict)
async def update_database_config(
    db_name: str,
    request: DatabaseConfigRequest,
    current_user: dict = Depends(get_current_user)
):
    """更新数据库配置"""
    try:
        logger.info(f"更新数据库配置: {db_name}")

        # 检查名称是否匹配
        if db_name != request.name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="URL中的名称与请求体中的名称不匹配"
            )

        # 转换为 DatabaseConfig 对象
        db_config = DatabaseConfig(**request.model_dump())

        # 更新配置
        success = await config_service.update_database_config(db_config)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"数据库配置 '{db_name}' 不存在"
            )

        # 记录操作日志
        await log_operation(
            user_id=current_user["id"],
            username=current_user.get("username", "unknown"),
            action_type=ActionType.CONFIG_MANAGEMENT,
            action=f"更新数据库配置: {db_name}",
            details={"name": request.name, "type": request.type, "host": request.host, "port": request.port}
        )

        return {"success": True, "message": "数据库配置更新成功"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新数据库配置失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新数据库配置失败: {str(e)}"
        )


@router.delete("/database/{db_name}", response_model=dict)
async def delete_database_config(
    db_name: str,
    current_user: dict = Depends(get_current_user)
):
    """删除数据库配置"""
    try:
        logger.info(f"删除数据库配置: {db_name}")

        # 删除配置
        success = await config_service.delete_database_config(db_name)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"数据库配置 '{db_name}' 不存在"
            )

        # 记录操作日志
        await log_operation(
            user_id=current_user["id"],
            username=current_user.get("username", "unknown"),
            action_type=ActionType.CONFIG_MANAGEMENT,
            action=f"删除数据库配置: {db_name}",
            details={"name": db_name}
        )

        return {"success": True, "message": "数据库配置删除成功"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除数据库配置失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"删除数据库配置失败: {str(e)}"
        )
