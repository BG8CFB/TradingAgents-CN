"""
按需刷新 API
"""

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.response import ok, fail

router = APIRouter(prefix="/api/cn/data", tags=["CN Data Refresh"])


class RefreshRequest(BaseModel):
    domains: Optional[list[str]] = None
    force: bool = False


@router.post("/refresh/{symbol}")
async def refresh_stock(symbol: str, request: RefreshRequest):
    """按需刷新指定股票的数据"""
    try:
        from app.data.core.interface import DataInterface

        di = DataInterface.get_instance()
        result = await di.refresh("CN", symbol, request.domains, request.force, 30)

        domain_dict = {}
        for d, dr in result.domains.items():
            domain_dict[d] = {
                "status": dr.status,
                "source": dr.source,
                "fallback_from": dr.fallback_from,
                "records": dr.record_count,
                "error": dr.error,
                "latency_ms": dr.latency_ms,
            }
        return ok(data={
            "symbol": result.symbol,
            "status": result.status,
            "domains": domain_dict,
            "duration_ms": result.total_latency_ms,
            "source": result.source_used,
            "fallback_from": result.fallback_from,
            "error": result.error,
        })
    except Exception as e:
        return fail(message=f"刷新失败: {e}", code=500)


@router.get("/refresh/{symbol}/status")
async def get_refresh_status(symbol: str):
    """获取指定股票各域的新鲜度状态"""
    from app.data.core.interface import DataInterface

    di = DataInterface.get_instance()
    domains = ["basic_info", "daily_quotes", "daily_indicators", "adj_factors", "financial_data", "news"]
    statuses = {}
    for domain in domains:
        try:
            result = await di.read("CN", symbol, domain)
            statuses[domain] = result.get("freshness", "unknown")
        except Exception:
            statuses[domain] = "unknown"

    return ok(data={"symbol": symbol, "domains": statuses})
