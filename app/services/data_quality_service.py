"""数据质量检查服务 — 通过 DataInterface 访问，供路由层调用。"""

import logging
import time
from typing import Dict, List, Tuple

from app.data.core.interface import DataInterface

logger = logging.getLogger(__name__)

# 质量总览短 TTL 缓存：单次要对每个域跑计数+最新日期查询。
# 键必须含 market 与 domains（三市场、不同域集合都走这个 service，否则串数据）。
_QUALITY_TTL_SECONDS = 60
_quality_cache: Dict[Tuple[str, Tuple[str, ...]], Tuple[float, Dict[str, Dict]]] = {}


async def get_quality_overview(market: str, domains: List[str]) -> Dict[str, Dict]:
    """带 60s TTL 缓存的质量概览入口。"""
    key = (market, tuple(domains))
    now = time.monotonic()
    cached = _quality_cache.get(key)
    if cached is not None and cached[0] > now:
        return cached[1]
    overview = await _build_quality_overview(market, domains)
    _quality_cache[key] = (now + _QUALITY_TTL_SECONDS, overview)
    return overview


async def _build_quality_overview(market: str, domains: List[str]) -> Dict[str, Dict]:
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
