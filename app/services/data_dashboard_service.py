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


async def get_dashboard_payload(market: str) -> Dict:
    """统一组装三市场 dashboard 载荷（cn/hk/us 路由共用，避免三份拷贝）。

    健康判定在数据层（DataInterface.get_domain_health → core/health.py），
    本方法只聚合；失败信号进入 degraded_fields，绝不静默吞掉。
    """
    di = DataInterface.get_instance()

    domain_health: Dict = {}
    try:
        domain_health = await di.get_domain_health(market)
    except Exception as e:
        logger.warning(f"获取 {market} 域健康失败: {e}", exc_info=True)
        domain_health = {"domains": [], "summary": {"degraded_fields": ["domain_health"]}}

    # 源健康序列化（无样本不伪造，见 core/health._serialize_source）
    from app.data.core.health import DomainHealthCalculator

    raw_health: List[Dict] = []
    try:
        raw_health = await di.get_source_health(market)
    except Exception as e:
        logger.warning(f"获取 {market} 源健康失败: {e}")
    source_health = [DomainHealthCalculator._serialize_source(h) for h in raw_health]

    summary = domain_health.get("summary", {})
    return {
        "domain_stats": {
            d.get("domain"): {
                "records": d.get("record_count", 0),
                "last_updated": d.get("last_sync_time"),
            }
            for d in domain_health.get("domains", [])
        },
        "domain_health": domain_health.get("domains", []),
        "source_health": source_health,
        "summary": {
            "overall": summary.get("overall", "unknown"),
            "total_domains": summary.get("total_domains", 0),
            "healthy_domains": summary.get("healthy_domains", 0),
            "warning_domains": summary.get("warning_domains", 0),
            "problem_domains": summary.get("problem_domains", 0),
            "unknown_domains": summary.get("unknown_domains", 0),
            "degraded_fields": summary.get("degraded_fields", []),
        },
    }
