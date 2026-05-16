"""
模型能力管理服务

提供模型能力评估、验证和推荐功能。
"""

from typing import Tuple, Dict, Optional, List, Any
from app.constants.model_capabilities import (
    DEFAULT_MODEL_CAPABILITIES,
    CAPABILITY_DESCRIPTIONS,
    ModelRole,
    ModelFeature
)
from app.core.unified_config import unified_config
import logging

logger = logging.getLogger(__name__)


class ModelCapabilityService:
    """模型能力管理服务"""

    def _parse_aggregator_model_name(self, model_name: str) -> Tuple[Optional[str], str]:
        """
        解析聚合渠道的模型名称

        Args:
            model_name: 模型名称，可能包含前缀（如 openai/gpt-4, anthropic/claude-3-sonnet）

        Returns:
            (原厂商, 原模型名) 元组
        """
        if "/" in model_name:
            parts = model_name.split("/", 1)
            if len(parts) == 2:
                provider_hint = parts[0].lower()
                original_model = parts[1]

                provider_map = {
                    "openai": "openai",
                    "anthropic": "anthropic",
                    "google": "google",
                    "deepseek": "deepseek",
                    "alibaba": "qwen",
                    "qwen": "qwen",
                    "zhipu": "zhipu",
                    "baidu": "baidu",
                    "moonshot": "moonshot"
                }

                provider = provider_map.get(provider_hint)
                return provider, original_model

        return None, model_name

    def _get_model_capability_with_mapping(self, model_name: str) -> Tuple[int, Optional[str]]:
        """
        获取模型能力等级（支持聚合渠道映射）

        Returns:
            (能力等级, 映射的原模型名) 元组
        """
        if model_name in DEFAULT_MODEL_CAPABILITIES:
            return DEFAULT_MODEL_CAPABILITIES[model_name]["capability_level"], None

        provider, original_model = self._parse_aggregator_model_name(model_name)

        if original_model and original_model != model_name:
            if original_model in DEFAULT_MODEL_CAPABILITIES:
                logger.info(f"🔄 聚合渠道模型映射: {model_name} -> {original_model}")
                return DEFAULT_MODEL_CAPABILITIES[original_model]["capability_level"], original_model

        return 2, None

    def get_model_capability(self, model_name: str) -> int:
        """
        获取模型的能力等级（支持聚合渠道模型映射）

        Returns:
            能力等级 (1-5)
        """
        try:
            llm_configs = unified_config.get_llm_configs()
            for config in llm_configs:
                if config.model_name == model_name:
                    return getattr(config, 'capability_level', 2)
        except Exception as e:
            logger.warning(f"从配置读取模型能力失败: {e}")

        capability, mapped_model = self._get_model_capability_with_mapping(model_name)
        if mapped_model:
            logger.info(f"✅ 使用映射模型 {mapped_model} 的能力等级: {capability}")

        return capability

    def get_model_config(self, model_name: str) -> Dict[str, Any]:
        """
        获取模型的完整配置信息（支持聚合渠道模型映射）

        Returns:
            模型配置字典
        """
        # 1. 优先从数据库配置读取
        try:
            from app.core.database import get_mongo_db_sync

            db = get_mongo_db_sync()
            collection = db.system_configs

            doc = collection.find_one({"is_active": True}, sort=[("version", -1)])

            if doc and "llm_configs" in doc:
                llm_configs = doc["llm_configs"]

                for config_dict in llm_configs:
                    if config_dict.get("model_name") == model_name:
                        features_str = config_dict.get('features', [])
                        features_enum = []
                        for feature_str in features_str:
                            try:
                                features_enum.append(ModelFeature(feature_str))
                            except ValueError:
                                logger.warning(f"⚠️ 未知的特性值: {feature_str}")

                        roles_str = config_dict.get('suitable_roles', ["both"])
                        roles_enum = []
                        for role_str in roles_str:
                            try:
                                roles_enum.append(ModelRole(role_str))
                            except ValueError:
                                logger.warning(f"⚠️ 未知的角色值: {role_str}")

                        if not roles_enum:
                            roles_enum = [ModelRole.BOTH]

                        return {
                            "model_name": config_dict.get("model_name"),
                            "capability_level": config_dict.get('capability_level', 2),
                            "suitable_roles": roles_enum,
                            "features": features_enum,
                            "performance_metrics": config_dict.get('performance_metrics', None)
                        }

        except Exception as e:
            logger.warning(f"从 MongoDB 读取模型信息失败: {e}", exc_info=True)

        # 2. 从默认映射表读取
        if model_name in DEFAULT_MODEL_CAPABILITIES:
            return DEFAULT_MODEL_CAPABILITIES[model_name]

        # 3. 聚合渠道模型映射
        provider, original_model = self._parse_aggregator_model_name(model_name)
        if original_model and original_model != model_name:
            if original_model in DEFAULT_MODEL_CAPABILITIES:
                logger.info(f"🔄 聚合渠道模型映射: {model_name} -> {original_model}")
                config = DEFAULT_MODEL_CAPABILITIES[original_model].copy()
                config["model_name"] = model_name
                config["_mapped_from"] = original_model
                return config

        # 4. 默认配置
        logger.warning(f"未找到模型 {model_name} 的配置，使用默认配置")
        return {
            "model_name": model_name,
            "capability_level": 2,
            "suitable_roles": [ModelRole.BOTH],
            "features": [ModelFeature.TOOL_CALLING],
            "performance_metrics": {"speed": 3, "cost": 3, "quality": 3}
        }

    def validate_model_pair(
        self,
        analyst_model: str,
        debate_model: str,
    ) -> Dict[str, Any]:
        """
        验证模型对是否适合分析任务

        Returns:
            验证结果字典，包含 valid, warnings, recommendations
        """
        logger.info(f"🔍 开始验证模型对: analyst={analyst_model}, debate={debate_model}")

        analyst_config = self.get_model_config(analyst_model)
        debate_config = self.get_model_config(debate_model)

        result = {
            "valid": True,
            "warnings": [],
            "recommendations": []
        }

        # 检查分析师模型角色适配
        analyst_roles = analyst_config.get("suitable_roles", [])
        if ModelRole.ANALYST not in analyst_roles and ModelRole.BOTH not in analyst_roles:
            result["warnings"].append(
                f"💡 模型 {analyst_model} 不是为一阶段分析优化的，可能影响数据收集效率"
            )

        # 检查分析师模型是否支持工具调用
        analyst_features = analyst_config.get("features", [])
        if ModelFeature.TOOL_CALLING not in analyst_features:
            result["valid"] = False
            result["warnings"].append(
                f"❌ 分析师模型 {analyst_model} 不支持工具调用，无法完成数据收集任务"
            )

        # 检查辩论模型角色适配
        debate_roles = debate_config.get("suitable_roles", [])
        if ModelRole.DEBATE not in debate_roles and ModelRole.BOTH not in debate_roles:
            result["warnings"].append(
                f"💡 模型 {debate_model} 不是为辩论推理优化的，可能影响分析质量"
            )

        # 检查辩论模型能力等级（建议 >= 2）
        debate_level = debate_config.get("capability_level", 2)
        if debate_level < 2:
            result["valid"] = False
            result["warnings"].append(
                f"❌ 辩论模型 {debate_model} (能力等级{debate_level}) 不满足最低要求(等级2)"
            )
            result["recommendations"].append(self._recommend_model("debate", 2))

        logger.info(f"🔍 验证结果: valid={result['valid']}, warnings={len(result['warnings'])}条")

        return result

    def recommend_models(self) -> Tuple[str, str]:
        """
        推荐合适的模型对（分析师模型 + 辩论模型）

        Returns:
            (analyst_model, debate_model) 元组
        """
        # 获取所有启用的模型
        try:
            llm_configs = unified_config.get_llm_configs()
            enabled_models = [c for c in llm_configs if c.enabled]
        except Exception as e:
            logger.error(f"获取模型配置失败: {e}")
            return self._get_default_models()

        if not enabled_models:
            logger.warning("没有启用的模型，使用默认配置")
            return self._get_default_models()

        # 筛选适合一阶段分析的模型
        analyst_candidates = []
        for m in enabled_models:
            roles = getattr(m, 'suitable_roles', [ModelRole.BOTH])
            features = getattr(m, 'features', [])

            if (ModelRole.ANALYST in roles or ModelRole.BOTH in roles) and \
               ModelFeature.TOOL_CALLING in features:
                analyst_candidates.append(m)

        # 筛选适合辩论推理的模型
        debate_candidates = []
        for m in enabled_models:
            roles = getattr(m, 'suitable_roles', [ModelRole.BOTH])

            if ModelRole.DEBATE in roles or ModelRole.BOTH in roles:
                debate_candidates.append(m)

        # 按性价比排序
        analyst_candidates.sort(
            key=lambda x: (
                getattr(x, 'capability_level', 2),
                -getattr(x, 'performance_metrics', {}).get("cost", 3) if getattr(x, 'performance_metrics', None) else 0
            ),
            reverse=True
        )

        debate_candidates.sort(
            key=lambda x: (
                getattr(x, 'capability_level', 2),
                getattr(x, 'performance_metrics', {}).get("quality", 3) if getattr(x, 'performance_metrics', None) else 0
            ),
            reverse=True
        )

        analyst_model = analyst_candidates[0].model_name if analyst_candidates else None
        debate_model = debate_candidates[0].model_name if debate_candidates else None

        if not analyst_model or not debate_model:
            return self._get_default_models()

        logger.info(
            f"🤖 推荐模型: analyst={analyst_model} (一阶段分析), debate={debate_model} (辩论推理)"
        )

        return analyst_model, debate_model

    def _get_default_models(self) -> Tuple[str, str]:
        """获取默认模型对"""
        try:
            analyst_model = unified_config.get_analyst_model()
            debate_model = unified_config.get_debate_model()
            logger.info(f"使用系统默认模型: analyst={analyst_model}, debate={debate_model}")
            return analyst_model, debate_model
        except Exception as e:
            logger.error(f"获取默认模型失败: {e}")
            return "qwen-turbo", "qwen-plus"

    def _recommend_model(self, model_type: str, min_level: int) -> str:
        """推荐满足要求的模型"""
        try:
            llm_configs = unified_config.get_llm_configs()
            for config in llm_configs:
                if config.enabled and getattr(config, 'capability_level', 2) >= min_level:
                    display_name = config.model_display_name or config.model_name
                    return f"建议使用: {display_name}"
        except Exception as e:
            logger.warning(f"推荐模型失败: {e}")

        return "建议升级模型配置"


# 单例
_model_capability_service = None


def get_model_capability_service() -> ModelCapabilityService:
    """获取模型能力服务单例"""
    global _model_capability_service
    if _model_capability_service is None:
        _model_capability_service = ModelCapabilityService()
    return _model_capability_service
