"""
模型能力分级系统

定义模型的能力等级、适用角色、特性标签等元数据，
用于智能匹配模型选择。

聚合渠道支持：
- 支持 302.AI、OpenRouter、One API 等聚合渠道
- 聚合渠道的模型名称格式：{provider}/{model}（如 openai/gpt-4）
- 系统会自动映射到原厂模型的能力配置
"""

from enum import IntEnum, Enum
from typing import Dict, List, Any, Tuple


class ModelCapabilityLevel(IntEnum):
    """模型能力等级（1-5级）"""
    BASIC = 1          # 基础：简单任务
    STANDARD = 2       # 标准：日常使用
    ADVANCED = 3       # 高级：复杂推理
    PROFESSIONAL = 4   # 专业：专业级分析
    FLAGSHIP = 5       # 旗舰：最强能力


class ModelRole(str, Enum):
    """模型角色类型"""
    ANALYST = "analyst"    # 一阶段分析师（低幻觉、数据收集、工具调用）
    DEBATE = "debate"      # 辩论推理（二至四阶段：辩论、风控、决策）
    BOTH = "both"          # 两者都适合


class ModelFeature(str, Enum):
    """模型特性标签"""
    TOOL_CALLING = "tool_calling"      # 支持工具调用（必需）
    LONG_CONTEXT = "long_context"      # 支持长上下文
    REASONING = "reasoning"            # 强推理能力
    VISION = "vision"                  # 支持视觉输入
    FAST_RESPONSE = "fast_response"    # 快速响应
    COST_EFFECTIVE = "cost_effective"  # 成本效益高


# 能力等级描述
CAPABILITY_DESCRIPTIONS = {
    1: "基础模型 - 适合一阶段分析师，响应快速，成本低",
    2: "标准模型 - 适合日常分析和常规任务，平衡性能和成本",
    3: "高级模型 - 适合辩论推理和复杂分析，质量较高",
    4: "专业模型 - 适合多轮辩论和专业级推理，高质量输出",
    5: "旗舰模型 - 最强能力，适合关键决策和全面分析"
}


# 常见模型的默认能力配置（用于初始化和参考）
DEFAULT_MODEL_CAPABILITIES: Dict[str, Dict[str, Any]] = {
    # ==================== 阿里百炼 (DashScope) ====================
    "qwen-turbo": {
        "capability_level": 1,
        "suitable_roles": [ModelRole.ANALYST],
        "features": [ModelFeature.TOOL_CALLING, ModelFeature.FAST_RESPONSE, ModelFeature.COST_EFFECTIVE],
        "performance_metrics": {"speed": 5, "cost": 5, "quality": 3},
        "description": "通义千问轻量版，适合一阶段分析师的数据收集和工具调用"
    },
    "qwen-plus": {
        "capability_level": 2,
        "suitable_roles": [ModelRole.BOTH],
        "features": [ModelFeature.TOOL_CALLING, ModelFeature.LONG_CONTEXT],
        "performance_metrics": {"speed": 4, "cost": 4, "quality": 4},
        "description": "通义千问标准版，平衡性能和成本"
    },
    "qwen-max": {
        "capability_level": 4,
        "suitable_roles": [ModelRole.BOTH],
        "features": [ModelFeature.TOOL_CALLING, ModelFeature.LONG_CONTEXT, ModelFeature.REASONING],
        "performance_metrics": {"speed": 3, "cost": 2, "quality": 5},
        "description": "通义千问旗舰版，强大推理能力"
    },
    "qwen3-max": {
        "capability_level": 5,
        "suitable_roles": [ModelRole.DEBATE],
        "features": [ModelFeature.TOOL_CALLING, ModelFeature.LONG_CONTEXT, ModelFeature.REASONING],
        "performance_metrics": {"speed": 2, "cost": 1, "quality": 5},
        "description": "通义千问长文本版，超长上下文"
    },
    
    # ==================== OpenAI ====================
    "gpt-3.5-turbo": {
        "capability_level": 1,
        "suitable_roles": [ModelRole.ANALYST],
        "features": [ModelFeature.TOOL_CALLING, ModelFeature.FAST_RESPONSE, ModelFeature.COST_EFFECTIVE],
        "performance_metrics": {"speed": 5, "cost": 5, "quality": 3},
        "description": "GPT-3.5 Turbo，快速且经济"
    },
    "gpt-4": {
        "capability_level": 3,
        "suitable_roles": [ModelRole.BOTH],
        "features": [ModelFeature.TOOL_CALLING, ModelFeature.REASONING],
        "performance_metrics": {"speed": 3, "cost": 3, "quality": 4},
        "description": "GPT-4，强大的推理能力"
    },
    "gpt-4-turbo": {
        "capability_level": 4,
        "suitable_roles": [ModelRole.BOTH],
        "features": [ModelFeature.TOOL_CALLING, ModelFeature.LONG_CONTEXT, ModelFeature.REASONING, ModelFeature.VISION],
        "performance_metrics": {"speed": 4, "cost": 2, "quality": 5},
        "description": "GPT-4 Turbo，更快更强"
    },
    "gpt-4o-mini": {
        "capability_level": 2,
        "suitable_roles": [ModelRole.BOTH],
        "features": [ModelFeature.TOOL_CALLING, ModelFeature.FAST_RESPONSE, ModelFeature.COST_EFFECTIVE],
        "performance_metrics": {"speed": 5, "cost": 5, "quality": 3},
        "description": "GPT-4o Mini，经济实惠"
    },
    "o1-mini": {
        "capability_level": 4,
        "suitable_roles": [ModelRole.DEBATE],
        "features": [ModelFeature.REASONING],
        "performance_metrics": {"speed": 2, "cost": 3, "quality": 5},
        "description": "O1 Mini，强推理模型"
    },
    "o1": {
        "capability_level": 5,
        "suitable_roles": [ModelRole.DEBATE],
        "features": [ModelFeature.REASONING],
        "performance_metrics": {"speed": 1, "cost": 1, "quality": 5},
        "description": "O1，最强推理能力"
    },
    "o4-mini": {
        "capability_level": 4,
        "suitable_roles": [ModelRole.DEBATE],
        "features": [ModelFeature.REASONING],
        "performance_metrics": {"speed": 2, "cost": 3, "quality": 5},
        "description": "O4 Mini，新一代推理模型"
    },
    
    # ==================== DeepSeek ====================
    "deepseek-v4-flash": {
        "capability_level": 4,
        "suitable_roles": [ModelRole.BOTH],
        "features": [ModelFeature.TOOL_CALLING, ModelFeature.LONG_CONTEXT, ModelFeature.COST_EFFECTIVE, ModelFeature.FAST_RESPONSE],
        "performance_metrics": {"speed": 5, "cost": 5, "quality": 4},
        "description": "DeepSeek V4 Flash，高速推理，性价比极高"
    },
    "deepseek-v4-pro": {
        "capability_level": 5,
        "suitable_roles": [ModelRole.DEBATE],
        "features": [ModelFeature.REASONING, ModelFeature.TOOL_CALLING, ModelFeature.LONG_CONTEXT],
        "performance_metrics": {"speed": 3, "cost": 3, "quality": 5},
        "description": "DeepSeek V4 Pro，深度推理，适合辩论与风控"
    },
    "deepseek-chat": {
        "capability_level": 3,
        "suitable_roles": [ModelRole.BOTH],
        "features": [ModelFeature.TOOL_CALLING, ModelFeature.LONG_CONTEXT, ModelFeature.COST_EFFECTIVE],
        "performance_metrics": {"speed": 4, "cost": 5, "quality": 4},
        "description": "DeepSeek Chat（将于 2026/07/24 弃用，请迁移至 deepseek-v4-flash）"
    },
    "deepseek-reasoner": {
        "capability_level": 4,
        "suitable_roles": [ModelRole.DEBATE],
        "features": [ModelFeature.REASONING, ModelFeature.LONG_CONTEXT],
        "performance_metrics": {"speed": 3, "cost": 4, "quality": 4},
        "description": "DeepSeek Reasoner（将于 2026/07/24 弃用，请迁移至 deepseek-v4-pro）"
    },
    
    # ==================== 百度文心 (Qianfan) ====================
    "ernie-3.5": {
        "capability_level": 2,
        "suitable_roles": [ModelRole.BOTH],
        "features": [ModelFeature.TOOL_CALLING],
        "performance_metrics": {"speed": 4, "cost": 4, "quality": 3},
        "description": "文心一言3.5，标准版本"
    },
    "ernie-4.0": {
        "capability_level": 3,
        "suitable_roles": [ModelRole.BOTH],
        "features": [ModelFeature.TOOL_CALLING, ModelFeature.REASONING],
        "performance_metrics": {"speed": 3, "cost": 3, "quality": 4},
        "description": "文心一言4.0，高级版本"
    },
    "ernie-4.0-turbo": {
        "capability_level": 4,
        "suitable_roles": [ModelRole.BOTH],
        "features": [ModelFeature.TOOL_CALLING, ModelFeature.REASONING, ModelFeature.FAST_RESPONSE],
        "performance_metrics": {"speed": 4, "cost": 2, "quality": 5},
        "description": "文心一言4.0 Turbo，旗舰版本"
    },
    
    # ==================== 智谱AI (GLM) ====================
    "glm-3-turbo": {
        "capability_level": 1,
        "suitable_roles": [ModelRole.ANALYST],
        "features": [ModelFeature.TOOL_CALLING, ModelFeature.FAST_RESPONSE, ModelFeature.COST_EFFECTIVE],
        "performance_metrics": {"speed": 5, "cost": 5, "quality": 3},
        "description": "智谱GLM-3 Turbo，快速版本"
    },
    "glm-4": {
        "capability_level": 3,
        "suitable_roles": [ModelRole.BOTH],
        "features": [ModelFeature.TOOL_CALLING, ModelFeature.REASONING],
        "performance_metrics": {"speed": 3, "cost": 3, "quality": 4},
        "description": "智谱GLM-4，标准版本"
    },
    "glm-4-plus": {
        "capability_level": 4,
        "suitable_roles": [ModelRole.BOTH],
        "features": [ModelFeature.TOOL_CALLING, ModelFeature.LONG_CONTEXT, ModelFeature.REASONING],
        "performance_metrics": {"speed": 3, "cost": 2, "quality": 5},
        "description": "智谱GLM-4 Plus，旗舰版本"
    },
    
    # ==================== Anthropic Claude ====================
    "claude-3-haiku": {
        "capability_level": 2,
        "suitable_roles": [ModelRole.ANALYST],
        "features": [ModelFeature.TOOL_CALLING, ModelFeature.FAST_RESPONSE],
        "performance_metrics": {"speed": 5, "cost": 4, "quality": 3},
        "description": "Claude 3 Haiku，快速版本"
    },
    "claude-3-sonnet": {
        "capability_level": 3,
        "suitable_roles": [ModelRole.BOTH],
        "features": [ModelFeature.TOOL_CALLING, ModelFeature.LONG_CONTEXT, ModelFeature.VISION],
        "performance_metrics": {"speed": 4, "cost": 3, "quality": 4},
        "description": "Claude 3 Sonnet，平衡版本"
    },
    "claude-3-opus": {
        "capability_level": 4,
        "suitable_roles": [ModelRole.BOTH],
        "features": [ModelFeature.TOOL_CALLING, ModelFeature.LONG_CONTEXT, ModelFeature.REASONING, ModelFeature.VISION],
        "performance_metrics": {"speed": 3, "cost": 2, "quality": 5},
        "description": "Claude 3 Opus，旗舰版本"
    },
    "claude-3.5-sonnet": {
        "capability_level": 5,
        "suitable_roles": [ModelRole.BOTH],
        "features": [ModelFeature.TOOL_CALLING, ModelFeature.LONG_CONTEXT, ModelFeature.REASONING, ModelFeature.VISION],
        "performance_metrics": {"speed": 4, "cost": 2, "quality": 5},
        "description": "Claude 3.5 Sonnet，最新旗舰"
    },

    # ==================== Google Gemini ====================
    "gemini-pro": {
        "capability_level": 3,
        "suitable_roles": [ModelRole.BOTH],
        "features": [ModelFeature.TOOL_CALLING, ModelFeature.REASONING],
        "performance_metrics": {"speed": 4, "cost": 4, "quality": 4},
        "description": "Gemini Pro，经典稳定版本"
    },
    "gemini-1.5-pro": {
        "capability_level": 4,
        "suitable_roles": [ModelRole.BOTH],
        "features": [ModelFeature.TOOL_CALLING, ModelFeature.LONG_CONTEXT, ModelFeature.REASONING, ModelFeature.VISION],
        "performance_metrics": {"speed": 4, "cost": 3, "quality": 5},
        "description": "Gemini 1.5 Pro，长上下文旗舰"
    },
    "gemini-1.5-flash": {
        "capability_level": 2,
        "suitable_roles": [ModelRole.ANALYST],
        "features": [ModelFeature.TOOL_CALLING, ModelFeature.FAST_RESPONSE, ModelFeature.COST_EFFECTIVE],
        "performance_metrics": {"speed": 5, "cost": 5, "quality": 3},
        "description": "Gemini 1.5 Flash，适合一阶段分析师"
    },
    "gemini-2.0-flash": {
        "capability_level": 4,
        "suitable_roles": [ModelRole.BOTH],
        "features": [ModelFeature.TOOL_CALLING, ModelFeature.LONG_CONTEXT, ModelFeature.REASONING, ModelFeature.FAST_RESPONSE],
        "performance_metrics": {"speed": 5, "cost": 3, "quality": 5},
        "description": "Gemini 2.0 Flash，新一代快速旗舰"
    },
    "gemini-2.5-flash-lite-preview-06-17": {
        "capability_level": 2,
        "suitable_roles": [ModelRole.ANALYST],
        "features": [ModelFeature.TOOL_CALLING, ModelFeature.FAST_RESPONSE, ModelFeature.COST_EFFECTIVE],
        "performance_metrics": {"speed": 5, "cost": 5, "quality": 3},
        "description": "Gemini 2.5 Flash Lite，适合轻量级分析"
    },

    # ==================== 月之暗面 (Moonshot) ====================
    "moonshot-v1-8k": {
        "capability_level": 2,
        "suitable_roles": [ModelRole.BOTH],
        "features": [ModelFeature.TOOL_CALLING],
        "performance_metrics": {"speed": 4, "cost": 4, "quality": 3},
        "description": "Moonshot V1 8K，标准版本"
    },
    "moonshot-v1-32k": {
        "capability_level": 3,
        "suitable_roles": [ModelRole.BOTH],
        "features": [ModelFeature.TOOL_CALLING, ModelFeature.LONG_CONTEXT],
        "performance_metrics": {"speed": 3, "cost": 3, "quality": 4},
        "description": "Moonshot V1 32K，长上下文版本"
    },
    "moonshot-v1-128k": {
        "capability_level": 4,
        "suitable_roles": [ModelRole.DEBATE],
        "features": [ModelFeature.TOOL_CALLING, ModelFeature.LONG_CONTEXT, ModelFeature.REASONING],
        "performance_metrics": {"speed": 2, "cost": 2, "quality": 5},
        "description": "Moonshot V1 128K，超长上下文旗舰"
    },
}


def get_model_capability_badge(level: int) -> Dict[str, str]:
    """获取能力等级徽章样式"""
    badges = {
        1: {"text": "基础", "color": "#909399", "icon": "⚡"},
        2: {"text": "标准", "color": "#409EFF", "icon": "📊"},
        3: {"text": "高级", "color": "#67C23A", "icon": "🎯"},
        4: {"text": "专业", "color": "#E6A23C", "icon": "🔥"},
        5: {"text": "旗舰", "color": "#F56C6C", "icon": "👑"}
    }
    return badges.get(level, badges[2])


def get_role_badge(role: ModelRole) -> Dict[str, str]:
    """获取角色徽章样式"""
    badges = {
        ModelRole.ANALYST: {"text": "一阶段分析师", "color": "success", "icon": "⚡"},
        ModelRole.DEBATE: {"text": "辩论推理", "color": "warning", "icon": "🧠"},
        ModelRole.BOTH: {"text": "通用", "color": "primary", "icon": "🎯"}
    }
    return badges.get(role, badges[ModelRole.BOTH])


def get_feature_badge(feature: ModelFeature) -> Dict[str, str]:
    """获取特性徽章样式"""
    badges = {
        ModelFeature.TOOL_CALLING: {"text": "工具调用", "color": "info", "icon": "🔧"},
        ModelFeature.LONG_CONTEXT: {"text": "长上下文", "color": "success", "icon": "📚"},
        ModelFeature.REASONING: {"text": "强推理", "color": "warning", "icon": "🧠"},
        ModelFeature.VISION: {"text": "视觉", "color": "primary", "icon": "👁️"},
        ModelFeature.FAST_RESPONSE: {"text": "快速", "color": "success", "icon": "⚡"},
        ModelFeature.COST_EFFECTIVE: {"text": "经济", "color": "success", "icon": "💰"}
    }
    return badges.get(feature, {"text": str(feature), "color": "info", "icon": "✨"})


# ==================== 聚合渠道配置 ====================

# 聚合渠道的默认配置
AGGREGATOR_PROVIDERS = {
    "302ai": {
        "display_name": "302.AI",
        "description": "302.AI 聚合平台，提供多厂商模型统一接口",
        "website": "https://302.ai",
        "api_doc_url": "https://doc.302.ai",
        "default_base_url": "https://api.302.ai/v1",
        "model_name_format": "{provider}/{model}",  # 如: openai/gpt-4
        "supported_providers": ["openai", "anthropic", "google", "deepseek", "qwen"]
    },
    "openrouter": {
        "display_name": "OpenRouter",
        "description": "OpenRouter 聚合平台，支持多种 AI 模型",
        "website": "https://openrouter.ai",
        "api_doc_url": "https://openrouter.ai/docs",
        "default_base_url": "https://openrouter.ai/api/v1",
        "model_name_format": "{provider}/{model}",
        "supported_providers": ["openai", "anthropic", "google", "meta", "mistral"]
    },
    "oneapi": {
        "display_name": "One API",
        "description": "One API 开源聚合平台",
        "website": "https://github.com/songquanpeng/one-api",
        "api_doc_url": "https://github.com/songquanpeng/one-api",
        "default_base_url": "http://localhost:3000/v1",  # 需要用户自行部署
        "model_name_format": "{model}",  # One API 通常不需要前缀
        "supported_providers": ["openai", "anthropic", "google", "azure", "claude"]
    },
    "newapi": {
        "display_name": "New API",
        "description": "New API 聚合平台",
        "website": "https://github.com/Calcium-Ion/new-api",
        "api_doc_url": "https://github.com/Calcium-Ion/new-api",
        "default_base_url": "http://localhost:3000/v1",
        "model_name_format": "{model}",
        "supported_providers": ["openai", "anthropic", "google", "azure", "claude"]
    }
}


def is_aggregator_model(model_name: str) -> bool:
    """
    判断是否为聚合渠道模型名称

    Args:
        model_name: 模型名称

    Returns:
        是否为聚合渠道模型
    """
    return "/" in model_name


def parse_aggregator_model(model_name: str) -> Tuple[str, str]:
    """
    解析聚合渠道模型名称

    Args:
        model_name: 模型名称（如 openai/gpt-4）

    Returns:
        (provider, model) 元组
    """
    if "/" in model_name:
        parts = model_name.split("/", 1)
        return parts[0], parts[1]
    return "", model_name

