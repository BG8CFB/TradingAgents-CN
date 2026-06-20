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
import functools
import logging
from typing import Any, Awaitable, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")

# 由 app/main.py lifespan 中设置
_main_loop: Optional[asyncio.AbstractEventLoop] = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    """注册主线程事件循环（在 app lifespan startup 时调用）"""
    global _main_loop
    _main_loop = loop


def get_main_loop() -> Optional[asyncio.AbstractEventLoop]:
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


# ── LLM 同步→异步桥接 ────────────────────────────────────────────


async def ainvoke(llm: Any, messages: Any, **kwargs: Any) -> Any:
    """异步执行 LLM 调用，统一替代所有 stage_2/3/4 中的 llm.invoke。

    - 若 llm 实现了 ``ainvoke``（langchain 标准异步接口）→ 直接 await
    - 否则通过 ``loop.run_in_executor`` 调度同步 ``invoke``

    所有引擎层节点都应通过此函数调用 LLM，禁止直接使用 ``llm.invoke``。

    Warning:
        对同步 LLM 走 ``run_in_executor`` 时，调用会运行在线程池中。
        LLM 客户端必须线程安全（OpenAI httpx 默认是线程安全的；
        DeepSeek 等基于 ``langchain_openai`` 的适配器也是线程安全的）。
        若自定义适配器使用了模块级猴子补丁之类的共享可变状态，
        需要自行保证线程安全或彻底改为 per-instance 方案。
    """
    if hasattr(llm, "ainvoke"):
        return await llm.ainvoke(messages, **kwargs)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, lambda: llm.invoke(messages, **kwargs)
    )


# ── 同步函数护栏 ──────────────────────────────────────────────────


def detect_nested_loop_and_raise(context: str = "") -> None:
    """在 sync 函数入口调用，发现当前线程已有事件循环则抛错指引。

    防止在 async 上下文中误调用同步包装函数（典型反模式）。
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    raise RuntimeError(
        f"检测到嵌套事件循环：当前线程已运行事件循环，禁止在 async 上下文中调用此同步函数。"
        f" context={context!r}。请改用对应的 async 版本，或通过 run_in_executor 调度。"
    )


def sync_only(func: Callable[..., T]) -> Callable[..., T]:
    """装饰器：标记函数仅可在同步上下文调用。

    若在事件循环中调用，抛出 RuntimeError 指引改用 async 版本。

    Example::

        @sync_only
        def get_mongo_db():
            ...
    """
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        detect_nested_loop_and_raise(
            context=f"{func.__module__}.{func.__qualname__}"
        )
        return func(*args, **kwargs)

    return wrapper


# ── 线程池桥接 ────────────────────────────────────────────────────


async def run_in_thread(
    func: Callable[..., R], *args: Any, **kwargs: Any
) -> R:
    """在默认线程池中执行同步函数，返回 awaitable。

    替代 ``loop.run_in_executor(None, functools.partial(func, *args, **kwargs))``。
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, functools.partial(func, *args, **kwargs)
    )
