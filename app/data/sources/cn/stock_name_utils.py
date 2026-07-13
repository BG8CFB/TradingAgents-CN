"""A 股股票名称查询工具 — 通过腾讯行情接口获取，供所有数据源共享使用。"""

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_name_cache: Dict[str, str] = {}


async def get_stock_name(symbol: str) -> Optional[str]:
    """异步获取股票名称 — 供 async 调用链使用，避免 run_async 嵌套死锁。

    优先查内存缓存，其次查 DataInterface，最后回退到腾讯行情同步接口。

    Args:
        symbol: 6位纯数字股票代码（不带后缀），如 "000001"
    """
    if symbol in _name_cache:
        return _name_cache[symbol]

    # 优先走 DataInterface（async 安全）
    try:
        from app.data.core.interface import DataInterface

        di = DataInterface.get_instance()
        result = await di.read("CN", "basic_info", symbol=symbol)
        data = result.get("data")
        if data:
            doc = data[0] if isinstance(data, list) and data else data
            name = doc.get("name")
            if name:
                _name_cache[symbol] = name
                return name
    except Exception as e:
        logger.debug(f"DataInterface 获取股票名称失败: {e}")

    # 回退到腾讯行情同步接口（在线程池中执行，不阻塞事件循环）
    return await _tencent_name_async(symbol)


async def _tencent_name_async(symbol: str) -> Optional[str]:
    """通过腾讯行情接口获取股票名称（async 包装）。"""
    import asyncio

    return await asyncio.to_thread(_tencent_name_sync, symbol)


def _tencent_name_sync(symbol: str) -> Optional[str]:
    """腾讯行情同步查询（内部函数，仅在 to_thread 中调用）。"""
    if symbol in _name_cache:
        return _name_cache[symbol]

    import requests as req

    if symbol.startswith(("6", "9")):
        code = f"sh{symbol}"
    elif symbol.startswith(("4", "8")):
        code = f"bj{symbol}"
    else:
        code = f"sz{symbol}"

    try:
        resp = req.get(f"http://qt.gtimg.cn/q={code}", timeout=5)
        parts = resp.text.split("~")
        if len(parts) > 1 and parts[1]:
            name = parts[1].strip()
            _name_cache[symbol] = name
            return name
    except Exception as e:
        logger.debug(f"腾讯行情接口获取股票名称失败: {e}")

    return None


def infer_exchange(symbol: str) -> str:
    """根据股票代码推断交易所。

    Args:
        symbol: 6位纯数字股票代码（不带后缀），如 "000001"

    Returns:
        交易所代码: "SSE"（上交所）/ "SZSE"（深交所）/ "BSE"（北交所）/ ""（未知）
    """
    if symbol.startswith(("60", "68", "90")):
        return "SSE"
    elif symbol.startswith(("00", "30", "20")):
        return "SZSE"
    elif symbol.startswith(("4", "8")):
        return "BSE"
    return ""


def get_stock_name_sync(symbol: str) -> Optional[str]:
    """通过腾讯行情接口快速获取股票名称（同步版本）。

    .. warning::
        本函数仅供纯同步上下文使用。若调用者已在事件循环线程中
        （如 FastAPI 请求处理或 async 数据源链），请改用
        :func:`get_stock_name`（async 版本），否则 ``run_async`` 会
        RuntimeError 或死锁。

    Args:
        symbol: 6位纯数字股票代码（不带后缀），如 "000001"
    """
    if symbol in _name_cache:
        return _name_cache[symbol]

    # 优先腾讯行情（纯同步 HTTP，无事件循环风险）
    name = _tencent_name_sync(symbol)
    if name:
        return name

    # 备选: 从 DataInterface 获取（需 run_async 桥接）
    try:
        from app.data.core.interface import DataInterface

        async def _read():
            di = DataInterface.get_instance()
            result = await di.read("CN", "basic_info", symbol=symbol)
            data = result.get("data")
            if data:
                doc = data[0] if isinstance(data, list) and data else data
                return doc.get("name")
            return None

        from app.core.async_utils import run_async
        name = run_async(_read())
        if name:
            _name_cache[symbol] = name
            return name
    except Exception as e:
        logger.debug(f"DataInterface 获取股票名称失败: {e}")

    return None
