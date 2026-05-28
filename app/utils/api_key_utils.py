"""
API Key 处理工具函数

提供统一的 API Key 验证、缩略等功能。
API Key 仅从数据库读取，不再从环境变量读取。
"""

from typing import Optional


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

