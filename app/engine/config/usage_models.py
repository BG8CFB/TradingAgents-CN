#!/usr/bin/env python3
"""
使用记录数据模型
用于 Token 使用统计和成本跟踪

注意：ModelConfig 已合并到 app.models.config.LLMConfig，保留别名以保持向后兼容。
"""

from dataclasses import dataclass
from typing import Optional

# ModelConfig 已从 app.models.config 导入别名，不再在此定义
# 避免与 Pydantic LLMConfig 重复维护默认值
from app.models.config import LLMConfig as ModelConfig  # noqa: F401


@dataclass
class UsageRecord:
    """使用记录"""
    timestamp: str  # 时间戳
    provider: str  # 供应商
    model_name: str  # 模型名称
    input_tokens: int  # 输入token数
    output_tokens: int  # 输出token数
    cost: float  # 成本
    currency: str = "CNY"  # 货币单位
    session_id: str = ""  # 会话ID
    analysis_type: str = "stock_analysis"  # 分析类型


@dataclass
class PricingConfig:
    """定价配置"""
    provider: str  # 供应商
    model_name: str  # 模型名称
    input_price_per_1k: float  # 输入token价格（每1000个token）
    output_price_per_1k: float  # 输出token价格（每1000个token）
    currency: str = "CNY"  # 货币单位

