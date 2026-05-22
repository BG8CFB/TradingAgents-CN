"""数据总览看板服务 — 通过 DataInterface 访问，供路由层调用。"""

import logging
from typing import Dict, List

from app.data.core.interface import DataInterface

logger = logging.getLogger(__name__)


async def get_domain_stats(market: str, domains: List[str]) -> Dict[str, Dict]:
    """获取各域统计信息（记录数 + 最后更新时间）。

    Returns:
        {domain: {"records": int, "last_updated": str|None}}
    """
    di = DataInterface.get_instance()
    return await di.get_domain_stats(market, domains)


async def get_daily_quotes_stats(market: str = "CN") -> Dict[str, int]:
    """获取日线行情集合统计（记录数 + 股票数）。"""
    di = DataInterface.get_instance()
    return await di.get_quotes_stats(market)
