"""
数据源健康监控 API
"""

from fastapi import APIRouter

from app.core.response import ok, fail

router = APIRouter(prefix="/api/cn/data", tags=["CN Source Health"])


@router.get("/source-health")
async def get_source_health():
    """获取数据源健康统计"""
    try:
        from app.services.cn_data_refresh_service import get_refresh_service
        svc = get_refresh_service()
        health = svc._router.get_source_health() if svc._router else []
        return ok(data=health)
    except Exception as e:
        return fail(message=f"查询失败: {e}", code=500)


@router.post("/source-health/{source}/{domain}/reset")
async def reset_circuit_breaker(source: str, domain: str):
    """重置指定数据源的熔断器"""
    try:
        from app.services.cn_data_refresh_service import get_refresh_service
        svc = get_refresh_service()
        if svc._router:
            svc._router.circuit_breaker.reset(source, domain)
            return ok(message=f"熔断器 {source}/{domain} 已重置")
        return fail(message="FallbackRouter 未初始化", code=400)
    except Exception as e:
        return fail(message=f"重置失败: {e}", code=500)
