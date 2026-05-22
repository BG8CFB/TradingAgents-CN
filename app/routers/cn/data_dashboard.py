"""
数据总览看板 API
"""

from fastapi import APIRouter

from app.core.response import ok

router = APIRouter(prefix="/api/cn/data", tags=["CN Data Dashboard"])

_DASHBOARD_DOMAINS = [
    "basic_info", "daily_quotes", "daily_indicators",
    "adj_factors", "financial", "market_quotes", "news",
]


@router.get("/dashboard")
async def get_dashboard():
    """数据总览看板：域状态 + 源健康 + 覆盖率"""

    # source_health 快照
    health = []
    try:
        from app.data.core.interface import DataInterface
        di = DataInterface.get_instance()
        health = await di.get_source_health("CN")
    except Exception:
        pass

    # 域覆盖率（通过 service 层）
    domain_stats = {}
    try:
        from app.services.data_dashboard_service import get_domain_stats
        domain_stats = await get_domain_stats("CN", _DASHBOARD_DOMAINS)
    except Exception:
        domain_stats = {d: {"records": 0, "last_updated": None} for d in _DASHBOARD_DOMAINS}

    return ok(data={
        "domain_stats": domain_stats,
        "source_health": health,
        "summary": {
            "total_domains": len(domain_stats),
            "healthy_sources": sum(1 for h in health if h.get("circuit_state") == "closed"),
        },
    })
