"""
数据质量检查 API — 通过 service 层访问数据
"""

import logging
from typing import Optional

from fastapi import APIRouter, Query

from app.core.response import ok, fail

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cn/data", tags=["CN Data Quality"])

_QUALITY_DOMAINS = ["daily_quotes", "daily_indicators", "adj_factors", "financial", "basic_info", "news"]
_CHECK_DOMAINS = ["daily_quotes", "daily_indicators", "financial", "basic_info"]


@router.get("/quality/overview")
async def get_quality_overview():
    """数据质量总览 — 各域记录数、完整率、最新日期"""
    try:
        from app.services.data_quality_service import get_quality_overview as svc_get_overview
        overview = await svc_get_overview("CN", _QUALITY_DOMAINS)
        return ok(data=overview)
    except Exception as e:
        return fail(message=f"查询失败: {e}", code=500)


@router.post("/quality/check")
async def trigger_quality_check(
    domain: Optional[str] = Query(None, description="指定域，为空检查全部"),
):
    """触发数据质量检查"""
    try:
        from app.services.data_quality_service import check_domain_quality

        results = {}
        domains = [domain] if domain else _CHECK_DOMAINS

        for d in domains:
            try:
                stats = await check_domain_quality("CN", d)
                results[d] = stats
            except Exception as e:
                results[d] = {"error": str(e)}

        return ok(data={"check_id": "inline", "results": results})

    except Exception as e:
        return fail(message=f"检查失败: {e}", code=500)
