"""
数据总览看板 API
"""

from fastapi import APIRouter

from app.core.response import ok

router = APIRouter(prefix="/api/cn/data", tags=["CN Data Dashboard"])


@router.get("/dashboard")
async def get_dashboard():
    """数据总览看板：域状态 + 源健康 + 覆盖率"""
    from app.data.processor.fallback_router import FallbackRouter

    # source_health 快照
    try:
        from app.data.processor.fallback_router import FallbackRouter as FR
        # 使用全局 FallbackRouter 单例（如果有）
        health = []
        # 从 DataRefreshService 获取（如果存在）
        try:
            from app.services.cn_data_refresh_service import get_refresh_service
            svc = get_refresh_service()
            if svc._router:
                health = svc._router.get_source_health()
        except Exception:
            pass
    except Exception:
        health = []

    # 域覆盖率
    domain_stats = {}
    try:
        from app.core.database import get_database
        from app.data.schema.collections import get_collection_name

        db = await get_database()
        domains = ["basic_info", "daily_quotes", "daily_indicators", "adj_factors", "financial", "market_quotes", "news"]

        for domain in domains:
            try:
                collection_name = get_collection_name("CN", domain)
                count = await db[collection_name].count_documents({})
                last_doc = await db[collection_name].find_one(
                    {}, {"updated_at": 1}, sort=[("updated_at", -1)],
                )
                domain_stats[domain] = {
                    "records": count,
                    "last_updated": last_doc.get("updated_at") if last_doc else None,
                }
            except Exception:
                domain_stats[domain] = {"records": 0, "last_updated": None}
    except Exception:
        pass

    return ok(data={
        "domain_stats": domain_stats,
        "source_health": health,
        "summary": {
            "total_domains": len(domain_stats),
            "healthy_sources": sum(1 for h in health if h.get("circuit_state") == "closed"),
        },
    })
