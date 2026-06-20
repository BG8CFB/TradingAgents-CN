"""
敏感信息脱敏工具。

统一提供用户名、token 在日志中输出时的标准化脱敏能力。

设计目标：
- 同一字段在所有日志中输出形式一致，便于审计与关联
- 脱敏后保留必要的可识别信息（前缀 + 长度），不破坏排障能力
- 不引入新的安全风险（token fingerprint 用 SHA256 截断，不可逆）
"""

from __future__ import annotations

import hashlib
import re
from typing import Iterable, List, Optional, Tuple

__all__ = [
    "mask_username",
    "token_fingerprint",
    "mask_uri_password",
    "mask_query_params",
]


# 用户名脱敏阈值：长度小于此值则全部用 * 替代
_USERNAME_MIN_KEEP = 3
# 用户名保留前缀长度
_USERNAME_KEEP_PREFIX = 2
# 用户名脱敏最大星号数（避免日志膨胀）
_USERNAME_MAX_MASKS = 6


def mask_username(name: Optional[str]) -> str:
    """用户名脱敏：保留前 2 字符 + *** + (len=N)。

    示例：
    - "admin" -> "ad**** (len=5)"
    - "li_ao" -> "li**** (len=5)"
    - "ab" -> "** (len=2)"
    - "" / None -> "***"

    Args:
        name: 原始用户名

    Returns:
        脱敏后的字符串
    """
    if not name:
        return "***"
    name = str(name)
    if len(name) < _USERNAME_MIN_KEEP:
        return f"{'*' * len(name)} (len={len(name)})"
    masks = min(len(name) - _USERNAME_KEEP_PREFIX, _USERNAME_MAX_MASKS)
    return f"{name[:_USERNAME_KEEP_PREFIX]}{'*' * masks} (len={len(name)})"


def token_fingerprint(token: Optional[str]) -> str:
    """生成 token 的不可逆指纹（SHA256 前 12 字符）。

    用于日志中标识 token 而不暴露原文。
    示例："a3f2c1b9e8d4"

    Args:
        token: 原始 token 字符串

    Returns:
        12 字符的 SHA256 指纹；token 为空时返回 "none"
    """
    if not token:
        return "none"
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()[:12]


# URI 中 password 段的匹配模式
# 同时支持 mongodb://user:pass@host 与 redis://:pass@host 形式
_URI_PASSWORD_PATTERN = re.compile(r"(://[^:/@?#]*:)([^@/?#]+)(@)")


def mask_uri_password(uri: Optional[str]) -> str:
    """脱敏 URI 中嵌入的 password 段。

    适用于 MongoDB URI、Redis URL 等含密码的连接串，在日志/响应体输出时脱敏。

    示例：
    - "mongodb://user:secret@host:27017/db" -> "mongodb://user:***@host:27017/db"
    - "redis://:mypwd@localhost:6379/0" -> "redis://:***@localhost:6379/0"
    - "mongodb://host:27017/db"（无密码）-> 原样返回
    - None / "" -> "***"

    Args:
        uri: 可能含密码的 URI 字符串

    Returns:
        脱敏后的 URI（password 段替换为 ***）
    """
    if not uri:
        return "***"
    return _URI_PASSWORD_PATTERN.sub(r"\1***\3", str(uri))


# 敏感 query 参数关键字（与 app.core.config.SENSITIVE_KEYWORDS 保持一致）
# 任何 key 含以下子串（不区分大小写）的 value 都会被脱敏
_QUERY_PARAM_SENSITIVE_KEYWORDS = (
    "password", "passwd", "pwd",
    "secret", "api_key", "apikey", "api-key",
    "token", "access_token", "refresh_token",
    "credential", "authorization",
)


def _is_sensitive_param(key: str) -> bool:
    """判断 query 参数 key 是否属于敏感字段。"""
    if not key:
        return False
    lower = key.lower()
    return any(kw in lower for kw in _QUERY_PARAM_SENSITIVE_KEYWORDS)


def mask_query_params(
    params: Optional[Iterable[Tuple[str, str]]],
) -> List[Tuple[str, str]]:
    """脱敏 query 参数中的敏感字段。

    用于 OperationLogMiddleware 落库前清理，避免 PASSWORD=xxx / TOKEN=xxx
    这类敏感信息原样写入 operation_logs 集合。

    Args:
        params: Starlette ``request.query_params.multi_items()`` 返回的
            ``list[tuple[str, str]]``

    Returns:
        新的 ``list[tuple[str, str]]``，敏感 value 替换为 ``"***"``，
        非敏感项原样保留；输入为 None 时返回空列表
    """
    if not params:
        return []
    masked: List[Tuple[str, str]] = []
    for key, value in params:
        if _is_sensitive_param(key):
            masked.append((key, "***"))
        else:
            masked.append((key, value))
    return masked
