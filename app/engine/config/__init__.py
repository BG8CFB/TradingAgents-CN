"""
配置管理模块

Phase 4A 重构说明：
- config_manager 已删除，token_tracker 迁移到 app.services.usage_statistics_service
- 数据模型（ModelConfig, PricingConfig, UsageRecord）仍从 usage_models 提供
"""

from .usage_models import ModelConfig, PricingConfig, UsageRecord


def __getattr__(name):
    if name == "token_tracker":
        from app.services.usage_statistics_service import token_tracker
        return token_tracker
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    'token_tracker',
    'ModelConfig',
    'PricingConfig',
    'UsageRecord'
]
