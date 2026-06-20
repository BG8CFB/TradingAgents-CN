"""
数据源异常映射器。

把不同数据源返回的原始异常（HTTP 状态码、Tushare 错误码、网络异常）
统一映射为 DataSourceError 子类，供 retry_policy 和 circuit_breaker 使用。

设计目标：
- 各数据源在 except 分支中只需调用一个映射函数，即可获得正确的异常子类
- 错误码差异化冷却（circuit_breaker._ERROR_COOLDOWN_MULTIPLIERS）才能真正生效
- retry_policy 的 is_retryable 才能正确判断

使用示例：

    try:
        result = await httpx_client.get(url)
        result.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise map_http_status_to_error(e.response.status_code, "tushare", "daily_quotes")
    except (asyncio.TimeoutError, ConnectionError) as e:
        raise map_network_exception(e, "tushare", "daily_quotes")
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Union

from app.data.sources.base.exceptions import (
    DataSourceError,
    DataSourceUnavailableError,
    DataNotFoundError,
    InsufficientCreditsError,
    NetworkError,
    RateLimitedError,
    TokenInvalidError,
)

logger = logging.getLogger(__name__)

__all__ = [
    "map_http_status_to_error",
    "map_tushare_code",
    "map_tushare_response",
    "map_network_exception",
    "is_empty_result",
]


# ──────────────────────────────────────────────────────────────
# HTTP 状态码映射
# ──────────────────────────────────────────────────────────────

# 429 限流
_HTTP_RATE_LIMITED = {429}
# 401 / 403 鉴权失败
_HTTP_AUTH_FAILED = {401, 403}
# 5xx 服务器错误
_HTTP_SERVER_ERROR = {500, 502, 503, 504}
# 4xx 客户端错误（除限流和鉴权外）
_HTTP_CLIENT_ERROR = {400, 404, 409, 422}
# 408 请求超时
_HTTP_TIMEOUT = {408, 504}


def map_http_status_to_error(
    status: int,
    source: str,
    domain: str,
    message: str = "",
    retry_after: int = 0,
) -> DataSourceError:
    """根据 HTTP 状态码返回对应的 DataSourceError 子类。

    Args:
        status: HTTP 状态码
        source: 数据源名（tushare/akshare/baostock/...）
        domain: 数据域（daily_quotes/basic_info/...）
        message: 可选错误描述
        retry_after: 限流场景的 Retry-After（秒）

    Returns:
        DataSourceError 的具体子类
    """
    if status in _HTTP_RATE_LIMITED:
        return RateLimitedError(source, domain, message, retry_after=retry_after)
    if status in _HTTP_AUTH_FAILED:
        return TokenInvalidError(source, domain, message)
    if status in _HTTP_TIMEOUT:
        return NetworkError(source, domain, message or f"HTTP {status} 超时")
    if status in _HTTP_SERVER_ERROR:
        return DataSourceUnavailableError(source, domain, message or f"HTTP {status}")
    if status in _HTTP_CLIENT_ERROR:
        return DataNotFoundError(source, domain, message or f"HTTP {status} 客户端错误")
    # 其他状态码默认走通用错误
    return DataSourceUnavailableError(source, domain, message or f"HTTP {status}")


# ──────────────────────────────────────────────────────────────
# Tushare 错误码映射
# ──────────────────────────────────────────────────────────────

# Tushare 常见错误码（参考官方文档）
_TUSHARE_RATE_LIMITED_CODES = frozenset({
    5003,    # 频次超限
    5004,    # 单日调用次数超限
})
_TUSHARE_AUTH_FAILED_CODES = frozenset({
    10001,   # 用户未登录或 token 无效
    10002,   # 权限不足
})
_TUSHARE_INSUFFICIENT_CREDITS_CODES = frozenset({
    40203,   # 积分不足
    40204,   # 没有权限访问该接口
})
_TUSHARE_DATA_NOT_FOUND_CODES = frozenset({
    40001,   # 股票代码不存在
    40002,   # 无数据
})


def map_tushare_code(
    code: Union[int, str, None],
    source: str,
    domain: str,
    message: str = "",
) -> Optional[DataSourceError]:
    """根据 Tushare 错误码返回对应的 DataSourceError 子类。

    Args:
        code: Tushare 接口返回的 code 字段（数字或字符串）
        source: 数据源名（一般为 "tushare"）
        domain: 数据域
        message: 可选错误描述

    Returns:
        DataSourceError 子类实例；如果 code 不在已知映射中则返回 None（表示是正常结果）
    """
    if code is None or code == 0:
        return None  # Tushare 成功响应 code=0
    try:
        code_int = int(code)
    except (ValueError, TypeError):
        return None

    if code_int in _TUSHARE_RATE_LIMITED_CODES:
        return RateLimitedError(source, domain, message)
    if code_int in _TUSHARE_AUTH_FAILED_CODES:
        return TokenInvalidError(source, domain, message)
    if code_int in _TUSHARE_INSUFFICIENT_CREDITS_CODES:
        return InsufficientCreditsError(source, domain, message)
    if code_int in _TUSHARE_DATA_NOT_FOUND_CODES:
        return DataNotFoundError(source, domain, message)
    return None


def map_tushare_response(
    response: Any,
    source: str,
    domain: str,
) -> Optional[DataSourceError]:
    """从 Tushare 标准响应字典中提取错误。

    Tushare 接口成功响应格式：{'code': 0, 'msg': '', 'data': {...}, 'fields': [...]}
    失败响应格式：{'code': 5003, 'msg': '...'}

    Args:
        response: Tushare 返回的字典或对象
        source: 数据源名
        domain: 数据域

    Returns:
        如果是错误响应则返回对应异常；否则返回 None
    """
    if response is None:
        return DataNotFoundError(source, domain, "Tushare 返回 None")
    if isinstance(response, dict):
        code = response.get("code")
        msg = response.get("msg", "")
        err = map_tushare_code(code, source, domain, msg)
        if err is not None:
            return err
        # 空数据校验
        data = response.get("data") or response.get("items")
        if data is None or (isinstance(data, (list, dict)) and len(data) == 0):
            return DataNotFoundError(source, domain, "Tushare 返回空数据")
    return None


# ──────────────────────────────────────────────────────────────
# 网络异常映射
# ──────────────────────────────────────────────────────────────


def map_network_exception(
    exc: Exception,
    source: str,
    domain: str,
    message: str = "",
) -> NetworkError:
    """把底层网络异常统一包装为 NetworkError。

    覆盖：
    - asyncio.TimeoutError
    - ConnectionError（含 ConnectionRefusedError / ConnectionResetError / BrokenPipeError）
    - httpx.ConnectError / httpx.ReadTimeout / httpx.ConnectTimeout
    - requests.Timeout / requests.ConnectionError

    Args:
        exc: 原始异常
        source: 数据源名
        domain: 数据域
        message: 可选错误描述

    Returns:
        NetworkError 实例
    """
    # 提取原始异常的类名作为错误信息的一部分
    exc_name = type(exc).__name__
    exc_msg = str(exc) or exc_name
    final_msg = message or f"{exc_name}: {exc_msg}"
    logger.debug(f"网络异常映射 [{source}/{domain}]: {final_msg}")
    return NetworkError(source, domain, final_msg)


# ──────────────────────────────────────────────────────────────
# 空结果检测
# ──────────────────────────────────────────────────────────────


def is_empty_result(result: Any) -> bool:
    """判断数据源返回的结果是否为空（应抛 DataNotFoundError）。

    覆盖：None、空 DataFrame、空 list、空 dict

    解耦说明：早期实现依赖 ``app.core.error_handling`` 处理 ``.empty``
    属性访问异常，但这会让 data.sources.base 反向依赖 app.core，违反分层约束。
    本实现改为内联 try/except + logger.debug，保持 data 层独立性。
    """
    if result is None:
        return True
    # pandas DataFrame / Series 的 empty 属性；少数自定义对象可能抛异常，降级为非空
    empty_attr = getattr(result, "empty", None)
    if empty_attr is not None:
        try:
            return bool(empty_attr)
        except Exception as exc:
            # 异常对象 .empty 访问失败：保守视为非空并继续走通用判定
            logger.debug("is_empty_result.empty_attr 访问异常: %s", exc)
    if isinstance(result, (list, dict, str)) and len(result) == 0:
        return True
    return False
