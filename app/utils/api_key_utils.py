"""
API Key 处理工具函数

提供统一的 API Key 验证、缩略、环境变量读取等功能。
"""

import os
from typing import Optional

from app.core.env import get_env


_PLACEHOLDER_EXACT_VALUES = {
    "***",
    "******",
    "xxx",
    "xxxxxx",
    "sk-xxx",
    "your-api-key",
    "your_api_key",
    "your key here",
    "your-key-here",
    "change-me",
    "changeme",
    "test",
    "null",
    "none",
}

_PLACEHOLDER_SUBSTRINGS = (
    "...",
    "your-",
    "your_",
    "placeholder",
    "replace-me",
    "replace_with",
    "<api",
    "[api",
)


def _normalize_api_key(api_key: Optional[str]) -> str:
    """标准化 API Key 输入。"""
    return (api_key or "").strip()


def is_placeholder_api_key(api_key: Optional[str]) -> bool:
    """判断是否为占位符、掩码值或截断后的展示值。"""
    normalized = _normalize_api_key(api_key)
    if not normalized:
        return False

    lowered = normalized.lower()
    if lowered in _PLACEHOLDER_EXACT_VALUES:
        return True

    return any(marker in lowered for marker in _PLACEHOLDER_SUBSTRINGS)


def is_valid_api_key(api_key: Optional[str]) -> bool:
    """
    判断 API Key 是否有效。

    这里不做厂商特定格式校验，只过滤空值、占位符和截断展示值。
    """
    normalized = _normalize_api_key(api_key)
    if not normalized:
        return False
    return not is_placeholder_api_key(normalized)


def truncate_api_key(api_key: Optional[str]) -> Optional[str]:
    """
    缩略 API Key，显示前6位和后6位
    
    示例：
        输入：'d1el869r01qghj41hahgd1el869r01qghj41hai0'
        输出：'d1el86...j41hai0'
    
    Args:
        api_key: 要缩略的 API Key
        
    Returns:
        str: 缩略后的 API Key，如果输入为空或长度 <= 12 则返回原值
    """
    normalized = _normalize_api_key(api_key)
    if not normalized or len(normalized) <= 12:
        return normalized or api_key

    return f"{normalized[:6]}...{normalized[-6:]}"


def get_env_api_key_for_provider(provider_name: str) -> Optional[str]:
    """
    从环境变量获取大模型厂家的 API Key
    
    环境变量名格式：{PROVIDER_NAME}_API_KEY
    
    Args:
        provider_name: 厂家名称（如 'deepseek', 'dashscope'）
        
    Returns:
        str: 环境变量中的 API Key，如果不存在或无效则返回 None
    """
    env_key_name = f"{provider_name.upper()}_API_KEY"
    env_key = get_env(env_key_name)

    if env_key and is_valid_api_key(env_key):
        return env_key

    return None


def get_env_api_key_for_datasource(ds_type: str) -> Optional[str]:
    """
    从环境变量获取数据源的 API Key
    
    数据源类型到环境变量名的映射：
    - tushare → TUSHARE_TOKEN
    - finnhub → FINNHUB_API_KEY
    - polygon → POLYGON_API_KEY
    - iex → IEX_API_KEY
    - quandl → QUANDL_API_KEY
    - alphavantage → ALPHAVANTAGE_API_KEY
    
    Args:
        ds_type: 数据源类型（如 'tushare', 'finnhub'）
        
    Returns:
        str: 环境变量中的 API Key，如果不存在或无效则返回 None
    """
    # 数据源类型到环境变量名的映射
    env_key_map = {
        "tushare": "TUSHARE_TOKEN",
        "finnhub": "FINNHUB_API_KEY",
        "polygon": "POLYGON_API_KEY",
        "iex": "IEX_API_KEY",
        "quandl": "QUANDL_API_KEY",
        "alphavantage": "ALPHAVANTAGE_API_KEY",
    }
    
    env_key_name = env_key_map.get(ds_type.lower())
    if not env_key_name:
        return None
    
    env_key = get_env(env_key_name)

    if env_key and is_valid_api_key(env_key):
        return env_key

    return None


def should_skip_api_key_update(api_key: Optional[str]) -> bool:
    """
    判断是否应该跳过 API Key 的更新。

    规则：
    - `None` 或明显的占位符/截断值：跳过，避免覆盖数据库中的真实密钥
    - 空字符串：不跳过，表示用户显式清空密钥
    - 其他非空字符串：允许更新
    """
    if api_key is None:
        return True

    normalized = _normalize_api_key(api_key)
    if normalized == "":
        return False

    return is_placeholder_api_key(normalized)

