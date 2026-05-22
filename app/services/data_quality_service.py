"""数据质量检查服务 — 通过 DataInterface 访问，供路由层调用。"""

import logging
from typing import Dict, List

from app.data.core.interface import DataInterface

logger = logging.getLogger(__name__)


async def get_quality_overview(market: str, domains: List[str]) -> Dict[str, Dict]:
    """获取各域质量概览（记录数、完整率、最新日期）。

    Returns:
        {domain: {"total_records", "missing_symbol", "completeness", "latest_date"}}
    """
    di = DataInterface.get_instance()
    return await di.get_quality_overview(market, domains)


async def check_domain_quality(market: str, domain: str) -> Dict:
    """对指定域执行完整质量检查。"""
    di = DataInterface.get_instance()
    return await di.check_domain_quality(market, domain)
