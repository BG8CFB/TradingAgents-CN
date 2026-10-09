"""工具层数据访问公共函数。

统一"读取 → 库空则触发按需刷新 → 再读"的回退模式，避免各工具在库空时
只返回"请先同步数据"。降级逻辑（选源/重试/熔断）留在数据层内部，
本模块只做编排：read 失败或空数据时调用 di.refresh 补数后重读一次。
"""

import logging
from typing import Any, Dict, Optional

from app.core.async_utils import run_async

logger = logging.getLogger(__name__)

_REFRESH_TIMEOUT = 30  # 秒，与 news 工具既有回退保持一致


def read_with_refresh(
    market: str,
    domain: str,
    symbol: Optional[str] = None,
    timeout: int = _REFRESH_TIMEOUT,
    **read_kwargs: Any,
) -> Optional[Dict[str, Any]]:
    """经 DataInterface 读取数据；库空时按需刷新该域后重读一次。

    仅限**同步上下文**（无运行中的事件循环）使用；async 调用方请直接用
    `read_with_refresh_async`，避免 run_async 桥在嵌套循环下退化报错。

    Args:
        market: 市场类型（CN/HK/US）
        domain: 数据域（daily_quotes / financial_data / ...）
        symbol: 股票代码（标准化后的 6 位/5 位/ticker）；无 symbol 时无法按需刷新
        timeout: 按需刷新超时秒数
        **read_kwargs: 透传给 di.read 的参数（start_date/end_date/filters 等）

    Returns:
        DataInterface.read 的完整结果 dict（含 data/freshness 等字段），
        两次读取均无数据时返回 None。不抛异常，失败只记 warning。
    """
    from app.data.core.interface import DataInterface

    di = DataInterface.get_instance()

    def _has_data(result: Optional[Dict[str, Any]]) -> bool:
        if not result:
            return False
        data = result.get("data")
        if data is None:
            return False
        if isinstance(data, (list, dict)):
            return len(data) > 0
        return bool(data)

    try:
        result = run_async(di.read(market, domain, symbol=symbol, **read_kwargs))
        if _has_data(result):
            return result
    except Exception as e:
        logger.warning(f"[data_access] 读取 {market}/{domain}/{symbol} 失败: {e}")

    # 库空/读取失败 → 按需刷新后重读（无 symbol 无法按需刷新，直接放弃）
    if not symbol:
        return None
    try:
        refresh_result = run_async(
            di.refresh(market, symbol, domains=[domain], force=True, timeout=timeout)
        )
        if not (refresh_result and refresh_result.domains.get(domain)):
            logger.info(f"[data_access] {market}/{domain}/{symbol} 按需刷新无结果（可能不支持该域或源不可用）")
            return None
    except Exception as e:
        logger.warning(f"[data_access] {market}/{domain}/{symbol} 按需刷新失败: {e}")
        return None

    try:
        result = run_async(di.read(market, domain, symbol=symbol, **read_kwargs))
        if _has_data(result):
            return result
    except Exception as e:
        logger.warning(f"[data_access] 刷新后重读 {market}/{domain}/{symbol} 失败: {e}")

    return None


async def read_with_refresh_async(
    market: str,
    domain: str,
    symbol: Optional[str] = None,
    timeout: int = _REFRESH_TIMEOUT,
    **read_kwargs: Any,
) -> Optional[Dict[str, Any]]:
    """`read_with_refresh` 的原生异步版本。

    工具 handler 改由 async 调用后，直接 await 数据层即可，**无需再经
    `run_async` 桥**——该桥在"当前已有运行中的事件循环但非注册主循环"的场景会
    退化到 `asyncio.run()` 并抛
    `asyncio.run() cannot be called from a running event loop`，
    导致库里明明有数据却读不到（实测：财务报表 / 资金流向 / 两融）。

    语义与同步版一致：库内无数据时按需刷新一次后重读；失败只记 warning 返回 None。
    """
    from app.data.core.interface import DataInterface

    di = DataInterface.get_instance()

    def _has_data(result: Optional[Dict[str, Any]]) -> bool:
        if not result:
            return False
        data = result.get("data")
        if data is None:
            return False
        if isinstance(data, (list, dict)):
            return len(data) > 0
        return bool(data)

    try:
        result = await di.read(market, domain, symbol=symbol, **read_kwargs)
        if _has_data(result):
            return result
    except Exception as e:
        logger.warning(f"[data_access] 读取 {market}/{domain}/{symbol} 失败: {e}")

    if not symbol:
        return None
    try:
        refresh_result = await di.refresh(market, symbol, domains=[domain], force=True, timeout=timeout)
        if not (refresh_result and refresh_result.domains.get(domain)):
            logger.info(f"[data_access] {market}/{domain}/{symbol} 按需刷新无结果（可能不支持该域或源不可用）")
            return None
    except Exception as e:
        logger.warning(f"[data_access] {market}/{domain}/{symbol} 按需刷新失败: {e}")
        return None

    try:
        result = await di.read(market, domain, symbol=symbol, **read_kwargs)
        if _has_data(result):
            return result
    except Exception as e:
        logger.warning(f"[data_access] 刷新后重读 {market}/{domain}/{symbol} 失败: {e}")

    return None
