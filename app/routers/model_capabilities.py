"""
模型能力管理API路由
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from app.services.model_capability_service import get_model_capability_service
from app.constants.model_capabilities import (
    DEFAULT_MODEL_CAPABILITIES,
    CAPABILITY_DESCRIPTIONS,
    ModelRole,
    ModelFeature,
    get_model_capability_badge,
    get_role_badge,
    get_feature_badge
)
from app.core.response import ok, fail
from app.services.config_service import config_service
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/model-capabilities", tags=["Model Capabilities"])


# ==================== 请求/响应模型 ====================

class ModelCapabilityInfo(BaseModel):
    """模型能力信息"""
    model_name: str
    capability_level: int
    suitable_roles: List[str]
    features: List[str]
    performance_metrics: Optional[Dict[str, Any]] = None
    description: Optional[str] = None


class ModelRecommendationRequest(BaseModel):
    """模型推荐请求"""
    pass


class ModelRecommendationResponse(BaseModel):
    """模型推荐响应"""
    analyst_model: str
    debate_model: str
    analyst_model_info: ModelCapabilityInfo
    debate_model_info: ModelCapabilityInfo
    reason: str


class ModelValidationRequest(BaseModel):
    """模型验证请求"""
    analyst_model: str
    debate_model: str


class ModelValidationResponse(BaseModel):
    """模型验证响应"""
    valid: bool
    warnings: List[str]
    recommendations: List[str]


class BatchInitRequest(BaseModel):
    """批量初始化请求"""
    overwrite: bool = Field(default=False, description="是否覆盖已有配置")


# ==================== API路由 ====================

@router.get("/default-configs")
async def get_default_model_configs():
    """
    获取所有默认模型能力配置

    返回预定义的常见模型能力配置，用于参考和初始化。
    """
    try:
        # 转换为可序列化的格式
        configs = {}
        for model_name, config in DEFAULT_MODEL_CAPABILITIES.items():
            configs[model_name] = {
                "model_name": model_name,
                "capability_level": config["capability_level"],
                "suitable_roles": [str(role) for role in config["suitable_roles"]],
                "features": [str(feature) for feature in config["features"]],
                "performance_metrics": config.get("performance_metrics"),
                "description": config.get("description")
            }

        return {
            "success": True,
            "data": configs,
            "message": "获取默认模型配置成功"
        }
    except Exception as e:
        logger.error(f"获取默认模型配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/capability-descriptions", response_model=dict)
async def get_capability_descriptions():
    """获取能力等级描述"""
    try:
        return ok(CAPABILITY_DESCRIPTIONS, "获取能力等级描述成功")
    except Exception as e:
        logger.error(f"获取能力等级描述失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/badges", response_model=dict)
async def get_all_badges():
    """
    获取所有徽章样式

    返回能力等级、角色、特性的徽章样式配置。
    """
    try:
        badges = {
            "capability_levels": {
                str(level): get_model_capability_badge(level)
                for level in range(1, 6)
            },
            "roles": {
                str(role): get_role_badge(role)
                for role in ModelRole
            },
            "features": {
                str(feature): get_feature_badge(feature)
                for feature in ModelFeature
            }
        }

        return ok(badges, "获取徽章样式成功")
    except Exception as e:
        logger.error(f"获取徽章样式失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/recommend", response_model=dict)
async def recommend_models():
    """
    推荐模型

    推荐最合适的模型对（分析师模型 + 辩论模型）。
    """
    try:
        capability_service = get_model_capability_service()

        analyst_model, debate_model = capability_service.recommend_models()

        logger.info(f"🔍 推荐模型: analyst={analyst_model}, debate={debate_model}")

        analyst_info = capability_service.get_model_config(analyst_model)
        debate_info = capability_service.get_model_config(debate_model)

        capability_desc = {
            1: "基础级",
            2: "标准级",
            3: "高级",
            4: "专业级",
            5: "旗舰级"
        }

        analyst_level_desc = capability_desc.get(analyst_info['capability_level'], "标准级")
        debate_level_desc = capability_desc.get(debate_info['capability_level'], "标准级")

        reason = (
            f"• 分析师模型：{analyst_level_desc}，低幻觉、数字敏感，适合一阶段数据收集\n"
            f"• 辩论模型：{debate_level_desc}，强逻辑推理，适合辩论与决策"
        )

        response_data = {
            "analyst_model": analyst_model,
            "debate_model": debate_model,
            "analyst_model_info": analyst_info,
            "debate_model_info": debate_info,
            "reason": reason
        }

        return ok(response_data, "模型推荐成功")
    except Exception as e:
        logger.error(f"模型推荐失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/validate", response_model=dict)
async def validate_models(request: ModelValidationRequest):
    """
    验证模型对

    验证选择的模型对是否适合分析任务。
    """
    try:
        capability_service = get_model_capability_service()

        validation = capability_service.validate_model_pair(
            request.analyst_model,
            request.debate_model,
        )

        return ok(validation, "模型验证完成")
    except Exception as e:
        logger.error(f"模型验证失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/batch-init", response_model=dict)
async def batch_init_capabilities(request: BatchInitRequest):
    """
    批量初始化模型能力

    为数据库中的模型配置自动填充能力参数。
    """
    try:
        system_config = await config_service.get_system_config()
        llm_configs = system_config.llm_configs if system_config else []

        updated_count = 0
        skipped_count = 0

        for config in llm_configs:
            model_name = config.model_name

            # 检查是否已有能力配置
            has_capability = hasattr(config, 'capability_level') and config.capability_level is not None

            if has_capability and not request.overwrite:
                skipped_count += 1
                continue

            # 从默认配置获取能力参数
            if model_name in DEFAULT_MODEL_CAPABILITIES:
                default_config = DEFAULT_MODEL_CAPABILITIES[model_name]

                # 更新配置
                config.capability_level = default_config["capability_level"]
                config.suitable_roles = [str(role) for role in default_config["suitable_roles"]]
                config.features = [str(feature) for feature in default_config["features"]]
                config.performance_metrics = default_config.get("performance_metrics")

                saved = await config_service.update_llm_config(config)
                if saved:
                    updated_count += 1
                    logger.info(f"已初始化并保存模型 {model_name} 的能力参数")
                else:
                    logger.error(f"保存模型 {model_name} 能力参数失败")
            else:
                logger.warning(f"模型 {model_name} 没有默认配置，跳过")
                skipped_count += 1

        return ok(
            {
                "updated_count": updated_count,
                "skipped_count": skipped_count,
                "total_count": len(llm_configs)
            },
            f"批量初始化完成：更新{updated_count}个，跳过{skipped_count}个"
        )
    except Exception as e:
        logger.error(f"批量初始化失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/model/{model_name}", response_model=dict)
async def get_model_capability(model_name: str):
    """
    获取指定模型的能力信息

    Args:
        model_name: 模型名称
    """
    try:
        capability_service = get_model_capability_service()
        config = capability_service.get_model_config(model_name)

        return ok(config, f"获取模型 {model_name} 能力信息成功")
    except Exception as e:
        logger.error(f"获取模型能力信息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

