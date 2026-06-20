"""
BaoStock 连接管理（login/logout 生命周期）

BaoStock 的 bs.login() / bs.logout() 操作的是模块级全局状态，
多个并发上下文同时调用 baostock_session() 会相互 logout，导致后续查询全部失败。

解决方案：引用计数 + 锁
- 第一个进入的上下文负责 login
- 最后一个退出的上下文负责 logout
- 中间的上下文既不 login 也不 logout，只共享连接

并发首登同步（关键修复）：
    历史实现里在 login 之前就把 ``_session_logged_in = True``，导致第二个并发
    协程看到 "已登录" 后直接进入业务查询，但此时第一个协程的 ``bs.login()``
    可能尚未完成（甚至失败）。修复方案：新增 ``_session_login_in_progress``
    标志区分"登录中"与"已成功"，第二个协程进入等待循环（每 50ms 轮询，
    最多 3 秒），等待 ``_session_logged_in`` 翻 True；如果首个 login 失败，
    ``_session_logged_in`` 翻 False，等待方也随之抛错。
"""
import asyncio
import logging
import threading
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

try:
    import baostock as bs
    BAOSTOCK_AVAILABLE = True
except ImportError:
    BAOSTOCK_AVAILABLE = False
    bs = None


# 全局状态：保护 baostock 模块级 login/logout
_session_lock = threading.Lock()
_session_refcount = 0
_session_logged_in = False
# 区分"login 进行中"与"login 已成功"，避免并发首登时第二个协程误以为已登录
_session_login_in_progress = False

# 等待方轮询参数：每 50ms 检查一次，最多等 3 秒（60 次）
_LOGIN_WAIT_INTERVAL = 0.05
_LOGIN_WAIT_MAX_RETRIES = 60


@asynccontextmanager
async def baostock_session():
    """BaoStock login/logout 上下文管理器（引用计数 + 互斥锁）。

    多个并发上下文共享同一份 login：
    - 第一个进入的协程调用 bs.login()
    - 中间的协程只增加引用计数（等待首个 login 完成后继续）
    - 最后一个退出的协程调用 bs.logout()
    """
    global _session_refcount, _session_logged_in, _session_login_in_progress

    if not BAOSTOCK_AVAILABLE:
        raise RuntimeError("BaoStock 库未安装")

    # 进入临界区：增量计数，必要时 login
    # 用 threading.Lock 而非 asyncio.Lock，因为 bs.login() 是同步阻塞调用，
    # 在 asyncio.to_thread 之外持锁是安全的（持锁时间极短）
    with _session_lock:
        _session_refcount += 1
        # 三态判定：
        # - 已登录 (_session_logged_in=True)：直接进入业务
        # - 登录中 (_session_login_in_progress=True)：等待方路径
        # - 未登录：本协程负责发起 login（发起方路径）
        if _session_logged_in:
            need_login = False
            is_waiter = False
        elif _session_login_in_progress:
            # 另一个协程正在 login：本协程不重复发起，等其结果
            need_login = False
            is_waiter = True
        else:
            # 首个进入的协程：占位 _session_login_in_progress，锁外执行 login
            need_login = True
            is_waiter = False
            _session_login_in_progress = True

    if need_login:
        try:
            await asyncio.to_thread(bs.login)
            with _session_lock:
                _session_login_in_progress = False
                _session_logged_in = True
            logger.debug("BaoStock 首次 login 成功")
        except Exception:
            # login 失败：恢复状态并抛错；等待方也会因 _session_logged_in 仍 False 而失败
            with _session_lock:
                _session_refcount -= 1
                _session_login_in_progress = False
                _session_logged_in = False
            raise

    elif is_waiter:
        # 等待首个 login 完成（每 50ms 轮询，最多 3 秒）
        # 这里不在 _session_lock 内 await（asyncio 中不能在持锁状态下 await），
        # 通过 sleep 让出事件循环给发起方协程执行 bs.login() 的机会
        success = False
        for _ in range(_LOGIN_WAIT_MAX_RETRIES):
            with _session_lock:
                if _session_logged_in:
                    success = True
                    break
                if not _session_login_in_progress:
                    # 发起方已退出但未置 logged_in=True，说明 login 失败
                    break
            await asyncio.sleep(_LOGIN_WAIT_INTERVAL)

        if not success:
            # 等待失败：减少引用计数后抛错，避免泄漏
            with _session_lock:
                _session_refcount -= 1
            raise RuntimeError("BaoStock 并发首登等待超时或失败")

    try:
        yield
    finally:
        # 离开临界区：减量计数，必要时 logout
        with _session_lock:
            _session_refcount -= 1
            if _session_refcount < 0:
                # 防御性编程：不应发生
                _session_refcount = 0
            need_logout = _session_refcount == 0 and _session_logged_in
            if need_logout:
                _session_logged_in = False
                _session_login_in_progress = False

        if need_logout:
            try:
                await asyncio.to_thread(bs.logout)
                logger.debug("BaoStock 最后一个引用 logout")
            except Exception as exc:
                logger.warning(f"BaoStock logout 失败: {exc}")


def is_available() -> bool:
    return BAOSTOCK_AVAILABLE
