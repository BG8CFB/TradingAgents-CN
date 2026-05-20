"""
按需刷新 API
"""

from typing import Optional

from fastapi import APIRouter, Query
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
        from app.services.cn_data_refresh_service import get_refresh_service
        svc = get_refresh_service()
        result = await svc.refresh(symbol, domains=request.domains, force=request.force)
        return ok(data=result.to_dict())
    except Exception as e:
        return fail(message=f"刷新失败: {e}", code=500)


@router.get("/refresh/{symbol}/status")
async def get_refresh_status(symbol: str):
    """获取指定股票各域的新鲜度状态"""
    from app.data.reader import check_freshness

    domains = ["basic_info", "daily_quotes", "daily_indicators", "adj_factors", "financial", "news"]
    statuses = {}
    for domain in domains:
        statuses[domain] = check_freshness("CN", symbol, domain)

    return ok(data={"symbol": symbol, "domains": statuses})
