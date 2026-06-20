"""统一异常处理工具（直接调用形式）。

消灭代码库中 ``except Exception: pass`` 与
``except Exception as e: logger.debug(...)`` 反模式，提供统一可观测的降级语义。

设计要点：

- ``safe_execute`` 用于同步函数；``safe_execute_async`` 用于协程
- 两者都是"直接调用形式"（非装饰器），适合一次性场景或不想修改目标函数签名的调用点
- 默认 ``log_level=WARNING``：降级场景应可见，但不污染 INFO
- ``default``：失败时返回的默认值（默认 None）
- ``context``：附加到日志的描述字符串
- ``logger``：可显式注入 logger；默认使用模块 logger
- ``catch``：捕获的异常类型元组（默认 ``(Exception,)``，禁止 ``BaseException``）

使用示例::

    from app.core.error_handling import safe_execute, safe_execute_async

    # 同步：失败返回默认值并记录 WARNING
    token = safe_execute(load_token, default="", context="load_token")

    # 异步：失败返回默认值并记录 WARNING
    result = await safe_execute_async(
        provider.fetch_data(symbol),
        default=None,
        context="provider.fetch_data",
    )

设计选择（为什么不提供装饰器形式）：
    早期版本提供过 ``@safe_call`` / ``@safe_async_call`` 装饰器，但全代码库
    零真实调用方（仅 docstring 示例引用）。装饰器会改变函数签名语义、
    增加 traceback 深度、让 IDE 跳转困难。直接调用形式更简单、更显式、
    更易调试。遵循 YAGNI，只保留实际使用的直接调用形式。
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Optional, TypeVar

T = TypeVar("T")

_default_logger = logging.getLogger("app.error_handling")


def _resolve_logger(logger: Optional[logging.Logger]) -> logging.Logger:
    return logger if logger is not None else _default_logger


def _validate_catch(catch: tuple) -> None:
    """校验 catch 元组的合法性，避免误捕获 BaseException 或空元组。"""
    if not catch:
        raise ValueError("catch 不能为空元组")
    if BaseException in catch and Exception not in catch:
        raise ValueError("禁止捕获 BaseException 但忽略 Exception")


def safe_execute(
    func: Callable[..., T],
    *args: Any,
    default: Any = None,
    log_level: int = logging.WARNING,
    context: str = "",
    logger: Optional[logging.Logger] = None,
    catch: tuple = (Exception,),
    **kwargs: Any,
) -> T:
    """同步直接调用：捕获异常并降级为返回 ``default``，同时记录日志。

    Args:
        func: 要调用的同步函数
        *args: 位置参数，透传给 ``func``
        default: 失败时返回的默认值
        log_level: 异常日志级别
        context: 附加到日志的描述字符串；默认用 ``func.__module__.__qualname__``
        logger: 可选 logger；默认使用 app.error_handling
        catch: 捕获的异常类型元组（默认 ``(Exception,)``）
        **kwargs: 关键字参数，透传给 ``func``

    Returns:
        ``func`` 的返回值；异常时返回 ``default``
    """
    _validate_catch(catch)
    log = _resolve_logger(logger)
    ctx = context or f"{func.__module__}.{func.__qualname__}"
    try:
        return func(*args, **kwargs)
    except catch as exc:
        log.log(
            log_level,
            "safe_execute[%s] 异常: %s: %s",
            ctx,
            type(exc).__name__,
            exc,
            exc_info=log_level <= logging.DEBUG,
        )
        return default


async def safe_execute_async(
    coro: Awaitable[T],
    *,
    default: Any = None,
    log_level: int = logging.WARNING,
    context: str = "",
    logger: Optional[logging.Logger] = None,
    catch: tuple = (Exception,),
) -> T:
    """异步直接调用：await 协程，捕获异常并降级为返回 ``default``，同时记录日志。

    Args:
        coro: 待 await 的协程对象（调用方负责构造，如 ``provider.fetch(x)``）
        default: 失败时返回的默认值
        log_level: 异常日志级别
        context: 附加到日志的描述字符串
        logger: 可选 logger；默认使用 app.error_handling
        catch: 捕获的异常类型元组（默认 ``(Exception,)``）

    Returns:
        协程结果；异常时返回 ``default``

    Example::

        result = await safe_execute_async(
            provider.fetch_data(symbol),
            default=None,
            context="provider.fetch_data",
        )
    """
    _validate_catch(catch)
    log = _resolve_logger(logger)
    ctx = context or "anonymous"
    try:
        return await coro
    except catch as exc:
        log.log(
            log_level,
            "safe_execute_async[%s] 异常: %s: %s",
            ctx,
            type(exc).__name__,
            exc,
            exc_info=log_level <= logging.DEBUG,
        )
        return default  # type: ignore[return-value]
