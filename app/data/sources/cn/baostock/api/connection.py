"""
BaoStock 连接管理（login/logout 生命周期）
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import baostock as bs
    BAOSTOCK_AVAILABLE = True
except ImportError:
    BAOSTOCK_AVAILABLE = False
    bs = None


@asynccontextmanager
async def baostock_session():
    """BaoStock login/logout 上下文管理器"""
    if not BAOSTOCK_AVAILABLE:
        raise RuntimeError("BaoStock 库未安装")

    await asyncio.to_thread(bs.login)
    try:
        yield
    finally:
        await asyncio.to_thread(bs.logout)


def is_available() -> bool:
    return BAOSTOCK_AVAILABLE
