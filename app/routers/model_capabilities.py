"""
模型能力管理API路由
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Dict, Any, Optional

from app.routers.auth_db import get_current_user
from app.services.model_capability_service import get_model_capability_service
from app.core.response import ok, safe_error_message
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/model-capabilities", tags=["Model Capabilities"])


# ==================== 请求/响应模型 ====================

class ModelCapabilityInfo(BaseModel):
    """模型能力信息"""
    model_name: str
    capability_level: int
    suitable_roles: list
    features: list
    performance_metrics: Optional[Dict[str, Any]] = None
    description: Optional[str] = None


class ModelRecommendationResponse(BaseModel):
    """模型推荐响应"""
    analyst_model: str
    debate_model: str
    analyst_model_info: ModelCapabilityInfo
    debate_model_info: ModelCapabilityInfo
    reason: str


# ==================== API路由 ====================

@router.post("/recommend", response_model=dict)
async def recommend_models(current_user: dict = Depends(get_current_user)):
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
        raise HTTPException(status_code=500, detail=safe_error_message(e, "模型推荐失败"))


@router.get("/model/{model_name}", response_model=dict)
async def get_model_capability(model_name: str, current_user: dict = Depends(get_current_user)):
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
        raise HTTPException(status_code=500, detail=safe_error_message(e, "获取模型能力信息失败"))

