"""
异步桥接工具

解决 Motor 客户端（绑定主线程事件循环）与 worker thread 中 asyncio.run() 的冲突。

调用链路：
  uvicorn 主线程 (event_loop)
    └→ run_in_executor(worker_thread)
        └→ sync 函数中需要调用 async Motor 操作
            → asyncio.run() 创建新循环 → Motor 客户端报 "attached to a different loop"
            → run_async() 使用 run_coroutine_threadsafe 回到主循环 → 正确执行

使用方式：
    from app.core.async_utils import run_async
    result = run_async(di.read("CN", "daily_quotes", symbol="000001.SZ"))
"""
import asyncio
import logging
from typing import Any, Awaitable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# 由 app/main.py lifespan 中设置
_main_loop: asyncio.AbstractEventLoop | None = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    """注册主线程事件循环（在 app lifespan startup 时调用）"""
    global _main_loop
    _main_loop = loop


def get_main_loop() -> asyncio.AbstractEventLoop | None:
    """获取主线程事件循环"""
    return _main_loop


def run_async(coro: Awaitable[T]) -> T:
    """
    在正确的异步上下文中执行协程。

    策略：
    1. 如果当前已在主事件循环的线程中 → 编程错误，应直接 await 而非调用 run_async
    2. 如果有注册的主事件循环（uvicorn），但当前在 worker thread → run_coroutine_threadsafe 调度到主循环
    3. 如果都没有（纯脚本）→ asyncio.run() 创建新循环
    """
    main_loop = _main_loop
    if main_loop is not None and main_loop.is_running():
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            # 没有运行中的事件循环——我们在 worker thread 中
            current_loop = None

        if current_loop is main_loop:
            # 主线程中已有事件循环，不能调用 run_async
            raise RuntimeError(
                "run_async() 不能在主线程的事件循环中调用。"
                "请直接 await 协程，或使用 run_in_executor 在 worker thread 中调用 run_async。"
            )

        # worker thread: 通过 run_coroutine_threadsafe 调度到主循环
        future = asyncio.run_coroutine_threadsafe(coro, main_loop)
        return future.result(timeout=60)

    # 没有主事件循环（纯脚本、测试）
    return asyncio.run(coro)
