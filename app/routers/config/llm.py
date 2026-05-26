"""
配置管理 - 大模型（LLM）子路由

包含：
- 大模型厂家 CRUD（GET/POST/PUT/DELETE /llm/providers）
- 厂家状态切换、模型列表获取、环境变量迁移、聚合渠道初始化、API 测试
- LLM 配置 CRUD（GET/POST /llm，DELETE /llm/{provider}/{model_name}）
- 设置默认大模型（POST /llm/set-default）
"""

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.routers.auth_db import get_current_user, require_admin
from app.models.user import User
from app.models.config import (
    LLMConfigRequest,
    LLMConfig,
    LLMProvider,
    LLMProviderRequest,
    LLMProviderResponse,
)
from app.services.config_service import config_service
from app.utils.api_key_utils import should_skip_api_key_update
from app.services.operation_log_service import log_operation
from app.models.operation_log import ActionType

logger = logging.getLogger("webapi")

router = APIRouter(tags=["Config"])


# ===== 共享辅助函数 =====

def _sanitize_llm_configs(items):
    """脱敏 LLM 配置中的 API Key"""
    try:
        return [LLMConfig(**{**i.model_dump(), "api_key": None}) for i in items]
    except Exception as e:
        logger.debug(f"LLM 配置脱敏失败: {e}")
        return items


class SetDefaultRequest(BaseModel):
    """设置默认配置请求"""
    name: str


# ==================== 大模型厂家管理 ====================

@router.get("/llm/providers", response_model=List[LLMProviderResponse])
async def get_llm_providers(
    current_user: User = Depends(get_current_user)
):
    """获取所有大模型厂家"""
    try:
        from app.utils.api_key_utils import (
            is_valid_api_key,
            truncate_api_key,
            get_env_api_key_for_provider
        )

        providers = await config_service.get_llm_providers()
        result = []

        for provider in providers:
            # 处理 API Key - 为了支持本地AI模型，不再验证有效性
            if provider.api_key:
                # 数据库中有 API Key，返回缩略版本
                api_key_display = truncate_api_key(provider.api_key)
            else:
                # 数据库中没有 API Key，尝试从环境变量读取
                env_key = get_env_api_key_for_provider(provider.name)
                if env_key:
                    # 环境变量中有 API Key，返回缩略版本
                    api_key_display = truncate_api_key(env_key)
                else:
                    api_key_display = None

            # 处理 API Secret - 为了支持本地AI模型，不再验证有效性
            if provider.api_secret:
                api_secret_display = truncate_api_key(provider.api_secret)
            else:
                # 注意：API Secret 通常不在环境变量中，所以这里只检查数据库
                api_secret_display = None

            result.append(
                LLMProviderResponse(
                    id=str(provider.id),
                    name=provider.name,
                    display_name=provider.display_name,
                    description=provider.description,
                    website=provider.website,
                    api_doc_url=provider.api_doc_url,
                    logo_url=provider.logo_url,
                    is_active=provider.is_active,
                    supported_features=provider.supported_features,
                    default_base_url=provider.default_base_url,
                    # 返回缩略的 API Key（前6位 + "..." + 后6位）
                    api_key=api_key_display,
                    api_secret=api_secret_display,
                    extra_config={
                        **provider.extra_config,
                        "has_api_key": bool(api_key_display),
                        "has_api_secret": bool(api_secret_display)
                    },
                    created_at=provider.created_at,
                    updated_at=provider.updated_at
                )
            )

        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取厂家列表失败: {str(e)}"
        )


@router.post("/llm/providers", response_model=dict)
async def add_llm_provider(
    request: LLMProviderRequest,
    current_user: User = Depends(require_admin)
):
    """添加大模型厂家"""
    try:
        sanitized = request.model_dump()
        # 占位符/截断值视为未填写，不存入数据库（运行时 fallback 到环境变量）
        if should_skip_api_key_update(sanitized.get('api_key')):
            sanitized['api_key'] = None
        if should_skip_api_key_update(sanitized.get('api_secret')):
            sanitized['api_secret'] = None
        provider = LLMProvider(**sanitized)
        provider_id = await config_service.add_llm_provider(provider)

        # 审计日志（忽略异常）
        try:
            await log_operation(
                user_id=str(current_user.get("id", "")),
                username=current_user.get("username", "unknown"),
                action_type=ActionType.CONFIG_MANAGEMENT,
                action="add_llm_provider",
                details={"provider_id": str(provider_id), "name": request.name},
                success=True,
            )
        except Exception as e:
            logger.debug(f"记录操作日志失败: {e}")
        return {
            "success": True,
            "message": "厂家添加成功",
            "data": {"id": str(provider_id)}
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"添加厂家失败: {str(e)}"
        )


@router.put("/llm/providers/{provider_id}", response_model=dict)
async def update_llm_provider(
    provider_id: str,
    request: LLMProviderRequest,
    current_user: User = Depends(require_admin)
):
    """更新大模型厂家"""
    try:
        from app.utils.api_key_utils import should_skip_api_key_update

        update_data = request.model_dump(exclude_unset=True)

        # 处理 API Key 的更新逻辑
        # 1. 如果 API Key 是空字符串，表示用户想清空密钥 -> 保存空字符串
        # 2. 如果 API Key 是占位符或截断的密钥（如 "sk-99054..."），则删除该字段（不更新）
        # 3. 如果 API Key 是有效的完整密钥，则更新
        if 'api_key' in update_data:
            api_key = update_data.get('api_key', '')
            # 如果应该跳过更新（占位符或截断的密钥），则删除该字段
            if should_skip_api_key_update(api_key):
                del update_data['api_key']
            # 如果是空字符串，保留（表示清空）
            # 如果是有效的完整密钥，保留（表示更新）

        if 'api_secret' in update_data:
            api_secret = update_data.get('api_secret', '')
            # 同样的逻辑处理 API Secret
            if should_skip_api_key_update(api_secret):
                del update_data['api_secret']

        success = await config_service.update_llm_provider(provider_id, update_data)

        if success:
            # 审计日志（忽略异常）
            try:
                await log_operation(
                    user_id=str(current_user.get("id", "")),
                    username=current_user.get("username", "unknown"),
                    action_type=ActionType.CONFIG_MANAGEMENT,
                    action="update_llm_provider",
                    details={"provider_id": provider_id, "changed_keys": list(request.model_dump().keys())},
                    success=True,
                )
            except Exception as _log_err:
                logger.debug(f"记录操作日志失败: {_log_err}")
            return {
                "success": True,
                "message": "厂家更新成功",
                "data": {}
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="厂家不存在"
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新厂家失败: {str(e)}"
        )


@router.delete("/llm/providers/{provider_id}", response_model=dict)
async def delete_llm_provider(
    provider_id: str,
    current_user: User = Depends(require_admin)
):
    """删除大模型厂家"""
    try:
        success = await config_service.delete_llm_provider(provider_id)

        if success:
            # 审计日志（忽略异常）
            try:
                await log_operation(
                    user_id=str(current_user.get("id", "")),
                    username=current_user.get("username", "unknown"),
                    action_type=ActionType.CONFIG_MANAGEMENT,
                    action="delete_llm_provider",
                    details={"provider_id": provider_id},
                    success=True,
                )
            except Exception as _log_err:
                logger.debug(f"记录操作日志失败: {_log_err}")
            return {
                "success": True,
                "message": "厂家删除成功",
                "data": {}
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="厂家不存在"
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"删除厂家失败: {str(e)}"
        )


@router.patch("/llm/providers/{provider_id}/toggle", response_model=dict)
async def toggle_llm_provider(
    provider_id: str,
    request: dict,
    current_user: User = Depends(require_admin)
):
    """切换大模型厂家状态"""
    try:
        is_active = request.get("is_active", True)
        success = await config_service.toggle_llm_provider(provider_id, is_active)

        if success:
            # 审计日志（忽略异常）
            try:
                await log_operation(
                    user_id=str(current_user.get("id", "")),
                    username=current_user.get("username", "unknown"),
                    action_type=ActionType.CONFIG_MANAGEMENT,
                    action="toggle_llm_provider",
                    details={"provider_id": provider_id, "is_active": bool(is_active)},
                    success=True,
                )
            except Exception as _log_err:
                logger.debug(f"记录操作日志失败: {_log_err}")
            return {
                "success": True,
                "message": f"厂家已{'启用' if is_active else '禁用'}",
                "data": {}
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="厂家不存在"
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"切换厂家状态失败: {str(e)}"
        )


@router.post("/llm/providers/{provider_id}/fetch-models", response_model=dict)
async def fetch_provider_models(
    provider_id: str,
    current_user: User = Depends(require_admin)
):
    """从厂家 API 获取模型列表"""
    try:
        result = await config_service.fetch_provider_models(provider_id)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取模型列表失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取模型列表失败: {str(e)}"
        )


@router.post("/llm/providers/migrate-env", response_model=dict)
async def migrate_env_to_providers(
    current_user: User = Depends(require_admin)
):
    """将环境变量配置迁移到厂家管理"""
    try:
        result = await config_service.migrate_env_to_providers()
        # 审计日志（忽略异常）
        try:
            await log_operation(
                user_id=str(current_user.get("id", "")),
                username=current_user.get("username", "unknown"),
                action_type=ActionType.CONFIG_MANAGEMENT,
                action="migrate_env_to_providers",
                details={
                    "migrated_count": result.get("migrated_count", 0),
                    "skipped_count": result.get("skipped_count", 0)
                },
                success=bool(result.get("success", False)),
            )
        except Exception as _log_err:
            logger.debug(f"记录操作日志失败: {_log_err}")

        return {
            "success": result["success"],
            "message": result["message"],
            "data": {
                "migrated_count": result.get("migrated_count", 0),
                "skipped_count": result.get("skipped_count", 0)
            }
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"环境变量迁移失败: {str(e)}"
        )


@router.post("/llm/providers/init-aggregators", response_model=dict)
async def init_aggregator_providers(
    current_user: User = Depends(require_admin)
):
    """初始化聚合渠道厂家配置（302.AI、OpenRouter等）"""
    try:
        result = await config_service.init_aggregator_providers()

        # 审计日志（忽略异常）
        try:
            await log_operation(
                user_id=str(current_user.get("id", "")),
                username=current_user.get("username", "unknown"),
                action_type=ActionType.CONFIG_MANAGEMENT,
                action="init_aggregator_providers",
                details={
                    "added_count": result.get("added", 0),
                    "skipped_count": result.get("skipped", 0)
                },
                success=bool(result.get("success", False)),
            )
        except Exception as _log_err:
            logger.debug(f"记录操作日志失败: {_log_err}")

        return {
            "success": result["success"],
            "message": result["message"],
            "data": {
                "added_count": result.get("added", 0),
                "skipped_count": result.get("skipped", 0)
            }
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"初始化聚合渠道失败: {str(e)}"
        )


@router.post("/llm/providers/{provider_id}/test", response_model=dict)
async def test_provider_api(
    provider_id: str,
    current_user: User = Depends(require_admin)
):
    """测试厂家API密钥"""
    try:
        logger.info(f"收到API测试请求 - provider_id: {provider_id}")
        result = await config_service.test_provider_api(provider_id)
        logger.info(f"API测试结果: {result}")
        return result
    except Exception as e:
        logger.error(f"测试厂家API失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"测试厂家API失败: {str(e)}"
        )


# ==================== 大模型配置管理 ====================

@router.get("/llm", response_model=List[LLMConfig])
async def get_llm_configs(
    current_user: User = Depends(require_admin)
):
    """获取所有大模型配置"""
    try:
        logger.info("开始获取大模型配置...")
        config = await config_service.get_system_config()

        if not config:
            logger.warning("系统配置为空，返回空列表")
            return []

        logger.info(f"系统配置存在，大模型配置数量: {len(config.llm_configs)}")

        # 如果没有大模型配置，创建一些示例配置
        if not config.llm_configs:
            logger.info("没有大模型配置，创建示例配置...")
            # 这里可以根据已有的厂家创建示例配置
            # 暂时返回空列表，让前端显示"暂无配置"

        # 获取所有供应商信息，用于过滤被禁用供应商的模型
        providers = await config_service.get_llm_providers()
        active_provider_names = {p.name for p in providers if p.is_active}

        # 过滤：只返回启用的模型 且 供应商也启用的模型
        filtered_configs = [
            llm_config for llm_config in config.llm_configs
            if llm_config.enabled and llm_config.provider in active_provider_names
        ]

        logger.info(f"过滤后的大模型配置数量: {len(filtered_configs)} (原始: {len(config.llm_configs)})")

        return _sanitize_llm_configs(filtered_configs)
    except Exception as e:
        logger.error(f"获取大模型配置失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取大模型配置失败: {str(e)}"
        )


@router.post("/llm", response_model=dict)
async def add_llm_config(
    request: LLMConfigRequest,
    current_user: User = Depends(require_admin)
):
    """添加或更新大模型配置"""
    try:
        logger.info(f"添加/更新大模型配置开始")
        logger.info(f"厂家: {request.provider}, 模型: {request.model_name}")

        # 创建LLM配置
        llm_config_data = request.model_dump()
        # 脱敏后记录日志（移除 api_key 等敏感字段）
        safe_log_data = {k: ("***" if "key" in k.lower() or "secret" in k.lower() else v) for k, v in llm_config_data.items()}
        logger.info(f"配置数据: {safe_log_data}")

        # 如果没有提供API密钥，按优先级获取：厂家配置 → 环境变量
        if not llm_config_data.get('api_key'):
            from app.utils.api_key_utils import get_env_api_key_for_provider

            logger.info(f"API密钥为空，按优先级获取: {request.provider}")

            # 1. 先从厂家配置获取
            providers = await config_service.get_llm_providers()
            logger.info(f"找到 {len(providers)} 个厂家配置")

            for p in providers:
                logger.info(f"   - 厂家: {p.name}, 有API密钥: {bool(p.api_key)}")

            provider_config = next((p for p in providers if p.name == request.provider), None)

            resolved_key = None
            if provider_config and provider_config.api_key:
                resolved_key = provider_config.api_key
                logger.info(f"从厂家配置获取API密钥 (长度: {len(resolved_key)})")

            # 2. 厂家没有则从环境变量获取
            if not resolved_key:
                env_key = get_env_api_key_for_provider(request.provider)
                if env_key:
                    resolved_key = env_key
                    logger.info(f"从环境变量获取API密钥 (长度: {len(resolved_key)})")

            # 不强制写入空字符串，保留 None 表示"使用环境变量 fallback"
            llm_config_data['api_key'] = resolved_key or None
            if not resolved_key:
                logger.info(f"厂家 {request.provider} 无数据库/环境变量API密钥，运行时将从环境变量动态获取")
        else:
            logger.info(f"使用提供的API密钥 (长度: {len(llm_config_data.get('api_key', ''))})")

        logger.info(f"最终配置数据: provider={llm_config_data.get('provider')}, model={llm_config_data.get('model_name')}")

        # 自动从 DEFAULT_MODEL_CAPABILITIES 填充缺失的能力数据
        try:
            from app.constants.model_capabilities import DEFAULT_MODEL_CAPABILITIES
            model_name = llm_config_data.get('model_name', '')
            # 支持聚合渠道模型名映射（如 openai/gpt-4 → gpt-4）
            lookup_name = model_name.split('/')[-1] if '/' in model_name else model_name
            if lookup_name in DEFAULT_MODEL_CAPABILITIES:
                defaults = DEFAULT_MODEL_CAPABILITIES[lookup_name]
                if not llm_config_data.get('capability_level') or llm_config_data.get('capability_level') == 2:
                    llm_config_data.setdefault('capability_level', defaults['capability_level'])
                if not llm_config_data.get('suitable_roles') or llm_config_data.get('suitable_roles') == ['both']:
                    llm_config_data.setdefault('suitable_roles', [str(r) for r in defaults['suitable_roles']])
                if not llm_config_data.get('features') or llm_config_data.get('features') == ['tool_calling']:
                    llm_config_data.setdefault('features', [str(f) for f in defaults['features']])
                if not llm_config_data.get('performance_metrics'):
                    llm_config_data.setdefault('performance_metrics', defaults.get('performance_metrics'))
                logger.info(f"已从 DEFAULT_MODEL_CAPABILITIES 自动填充模型 {model_name} 的能力数据")
        except Exception as e:
            logger.warning(f"自动填充模型能力数据失败: {e}")

        # 确保 suitable_roles 有默认值
        if not llm_config_data.get('suitable_roles'):
            llm_config_data['suitable_roles'] = ['both']

        # 为了支持本地AI模型，允许任何 API Key（包括空值）
        if 'api_key' in llm_config_data:
            api_key = llm_config_data.get('api_key', '')
            # 为了支持本地AI模型，保留用户输入的任何值（包括空值）
            llm_config_data['api_key'] = api_key

        # 尝试创建LLMConfig对象
        try:
            llm_config = LLMConfig(**llm_config_data)
            logger.info(f"LLMConfig对象创建成功")
        except Exception as e:
            logger.error(f"LLMConfig对象创建失败: {e}")
            logger.error(f"失败的数据: {llm_config_data}")
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"配置数据验证失败: {str(e)}"
            )

        # 保存配置
        success = await config_service.update_llm_config(llm_config)

        if success:
            logger.info(f"大模型配置更新成功: {llm_config.provider}/{llm_config.model_name}")

            # 同步定价配置到 tradingagents
            try:
                from app.core.config_bridge import sync_pricing_config_now
                await sync_pricing_config_now()
                logger.info(f"定价配置已同步到 tradingagents")
            except Exception as e:
                logger.warning(f"同步定价配置失败: {e}")

            # 审计日志（忽略异常）
            try:
                await log_operation(
                    user_id=str(current_user.get("id", "")),
                    username=current_user.get("username", "unknown"),
                    action_type=ActionType.CONFIG_MANAGEMENT,
                    action="update_llm_config",
                    details={"provider": llm_config.provider, "model_name": llm_config.model_name},
                    success=True,
                )
            except Exception as _log_err:
                logger.debug(f"记录操作日志失败: {_log_err}")
            return {"message": "大模型配置更新成功", "model_name": llm_config.model_name}
        else:
            logger.error(f"大模型配置保存失败")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="大模型配置更新失败"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"添加大模型配置异常: {e}")
        import traceback
        logger.error(f"异常堆栈: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"添加大模型配置失败: {str(e)}"
        )


@router.delete("/llm/{provider}/{model_name}")
async def delete_llm_config(
    provider: str,
    model_name: str,
    current_user: User = Depends(require_admin)
):
    """删除大模型配置"""
    try:
        logger.info(f"删除大模型配置请求 - provider: {provider}, model_name: {model_name}")
        success = await config_service.delete_llm_config(provider, model_name)

        if success:
            logger.info(f"大模型配置删除成功 - {provider}/{model_name}")

            # 同步定价配置到 tradingagents
            try:
                from app.core.config_bridge import sync_pricing_config_now
                await sync_pricing_config_now()
                logger.info(f"定价配置已同步到 tradingagents")
            except Exception as e:
                logger.warning(f"同步定价配置失败: {e}")

            # 审计日志（忽略异常）
            try:
                await log_operation(
                    user_id=str(current_user.get("id", "")),
                    username=current_user.get("username", "unknown"),
                    action_type=ActionType.CONFIG_MANAGEMENT,
                    action="delete_llm_config",
                    details={"provider": provider, "model_name": model_name},
                    success=True,
                )
            except Exception as _log_err:
                logger.debug(f"记录操作日志失败: {_log_err}")
            return {"message": "大模型配置删除成功"}
        else:
            logger.warning(f"未找到大模型配置 - {provider}/{model_name}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="大模型配置不存在"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除大模型配置异常 - {provider}/{model_name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"删除大模型配置失败: {str(e)}"
        )


@router.post("/llm/set-default")
async def set_default_llm(
    request: SetDefaultRequest,
    current_user: User = Depends(require_admin)
):
    """设置默认大模型"""
    try:
        success = await config_service.set_default_llm(request.name)
        if success:
            # 审计日志（忽略异常）
            try:
                await log_operation(
                    user_id=str(current_user.get("id", "")),
                    username=current_user.get("username", "unknown"),
                    action_type=ActionType.CONFIG_MANAGEMENT,
                    action="set_default_llm",
                    details={"name": request.name},
                    success=True,
                )
            except Exception as _log_err:
                logger.debug(f"记录操作日志失败: {_log_err}")
            return {"message": "默认大模型设置成功", "default_llm": request.name}
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="指定的大模型不存在"
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"设置默认大模型失败: {str(e)}"
        )
