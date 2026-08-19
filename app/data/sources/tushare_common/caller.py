"""call_tushare — Tushare 调用模板收敛。

三市场 29 个 fetch 函数原先复制同一段 15-18 行的
``asyncio.to_thread → map_network_exception → map_tushare_code →
is_empty_result → DataNotFoundError`` 模板；本模块把它收敛为一个帮助函数，
各 fetch 函数保持公开签名与返回语义不变，函数体改为一行委托。
"""

import asyncio
import logging
from typing import Any, Optional

from app.data.sources.base.exceptions import (
    DataNotFoundError,
    DataSourceUnavailableError,
)
from app.data.sources.base.mappers import (
    is_empty_result,
    map_network_exception,
    map_tushare_code,
)

logger = logging.getLogger(__name__)


def _class_attr(obj: Any, name: str):
    """只从类层次取属性，绕过 tushare DataApi 的万能 __getattr__。

    DataApi.__getattr__ 对任意属性名都返回 partial(query(name))，
    普通 getattr(api, "get_api") 会变成执行 query("get_api") 并抛
    "请指定正确的接口名"（HK/US fetch 传入裸 pro_api 时全部踩中）。
    """
    for klass in type(obj).__mro__:
        if name in vars(klass):
            return vars(klass)[name]
    return None


def _resolve_api(api_or_client: Any):
    """把 api / TushareClient / TushareConnection 统一解析为可用 pro_api。

    返回 None 表示调用方不可用（未连接 / 未配置 Token），
    调用模板按参数前置校验处理，直接返回 None。
    """
    if api_or_client is None:
        return None
    # TushareClient（共享客户端）— 必须走类属性判断（见 _class_attr 注释）
    get_api = _class_attr(api_or_client, "get_api")
    if callable(get_api):
        return get_api(api_or_client)
    is_available = _class_attr(api_or_client, "is_available")
    if callable(is_available):
        if not is_available(api_or_client):
            return None
        return getattr(api_or_client, "api", None)
    # CN 侧 TushareConnection 兼容：具备 is_available() + api 属性
    # （同样必须走 _class_attr，避免 DataApi __getattr__ 假阳性）
    is_available = _class_attr(api_or_client, "is_available")
    if callable(is_available):
        if not is_available(api_or_client):
            return None
        return getattr(api_or_client, "api", None)
    # 已是裸 pro_api 实例
    return api_or_client


async def call_tushare(
    api_or_client: Any,
    method_name: str,
    source: str,
    domain: str,
    context: str = "",
    **params,
) -> Optional[Any]:
    """执行一次 Tushare 接口调用，统一异常映射与空结果判定。

    Args:
        api_or_client: pro_api 实例 / TushareClient / TushareConnection。
            不可用时直接返回 None（参数前置校验，不抛异常）。
        method_name: Tushare 接口名（如 "hk_daily" / "us_basic" / "adj_factor"）。
        source: 数据源名（异常载体，如 "tushare_hk"）。
        domain: 数据域（异常载体，如 "daily_quotes"）。
        context: 错误/日志消息中的上下文（如 ts_code / exchange）。
        **params: 透传给接口的参数（调用方负责日期压缩等预处理）。

    Returns:
        原始 DataFrame；接口不存在时返回 None。

    Raises:
        NetworkError / RateLimitedError / TokenInvalidError /
        InsufficientCreditsError / DataNotFoundError / DataSourceUnavailableError
    """
    api = _resolve_api(api_or_client)
    if api is None:
        return None

    method = getattr(api, method_name, None)
    if method is None:
        logger.error(f"{source} 不支持的接口: {method_name}")
        return None

    try:
        df = await asyncio.to_thread(method, **params)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        # 网络异常：可重试
        raise map_network_exception(exc, source, domain)
    except Exception as exc:
        # Tushare 业务异常（限流/token/积分等）：按错误码分类
        error_code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
        mapped = map_tushare_code(error_code, source, domain, str(exc))
        if mapped is not None:
            raise mapped
        raise DataSourceUnavailableError(source, domain, f"{f'{context}: ' if context else ''}{exc}")

    # 空结果（业务正确但无数据）— 用 DataNotFoundError 表示
    if is_empty_result(df):
        logger.warning(f"{source} {domain} 返回空数据: {context or method_name}")
        raise DataNotFoundError(source, domain, f"{context or method_name} 无数据")

    logger.info(f"{source} {domain}({method_name}): {context or ''} {len(df)} 条".strip())
    return df
