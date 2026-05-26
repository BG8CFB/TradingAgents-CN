"""Toolkit 辅助函数 — 被 toolkit_*.py 子模块共享。"""

import asyncio
import concurrent.futures

import pandas as pd

from app.data.core.interface import DataInterface
from app.utils.logging_init import get_logger

logger = get_logger("agents")


def _run_async(coro):
    """安全地在同步上下文中执行异步协程。

    当已有运行中的事件循环时（如 FastAPI 中），使用线程池执行；
    否则直接使用 asyncio.run()。
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result(timeout=60)
    else:
        return asyncio.run(coro)


def _get_stock_data_sync(market, symbol, start_date=None, end_date=None):
    """同步获取股票日线数据，返回格式化的字符串。"""
    try:
        di = DataInterface.get_instance()
        result = _run_async(
            di.read(
                market,
                "daily_quotes",
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
            )
        )
        data = result.get("data")
        if data:
            return pd.DataFrame(data).to_string()
    except Exception as e:
        logger.debug(f"获取股票日线数据失败: {e}")
    return None


def _get_stock_info_sync(market, symbol):
    """同步获取股票基础信息，返回格式化的字符串。"""
    try:
        di = DataInterface.get_instance()
        result = _run_async(di.read(market, "basic_info", symbol=symbol))
        data = result.get("data")
        if data:
            doc = data[0] if isinstance(data, list) and data else data
            lines = [f"股票代码: {doc.get('symbol', symbol)}"]
            if doc.get("name"):
                lines.append(f"股票名称: {doc.get('name')}")
            if doc.get("industry"):
                lines.append(f"行业: {doc.get('industry')}")
            if doc.get("exchange"):
                lines.append(f"交易所: {doc.get('exchange')}")
            return "\n".join(lines)
    except Exception as e:
        logger.debug(f"获取股票基础信息失败: {e}")
    return None


def _get_us_news_sync(symbol):
    """同步获取美股新闻数据，返回格式化的字符串。"""
    try:
        di = DataInterface.get_instance()
        result = _run_async(di.read("US", "news", symbol=symbol.upper()))
        data = result.get("data")
        if data:
            return str(data)
    except Exception as e:
        logger.debug(f"获取美股新闻数据失败: {e}")
    return None


def _get_us_daily_quotes_sync(symbol, start_date=None, end_date=None):
    """同步获取美股日线数据，返回 DataFrame 字符串。"""
    try:
        di = DataInterface.get_instance()
        result = _run_async(
            di.read(
                "US",
                "daily_quotes",
                symbol=symbol.upper(),
                start_date=start_date,
                end_date=end_date,
            )
        )
        data = result.get("data")
        if data:
            return pd.DataFrame(data).to_string()
    except Exception as e:
        logger.debug(f"获取美股日线数据失败: {e}")
    return None
