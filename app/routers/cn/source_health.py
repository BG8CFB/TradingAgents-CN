"""数据源健康监控 API。"""

from fastapi import APIRouter

from app.core.response import ok, fail

router = APIRouter(prefix="/api/cn/data", tags=["CN Source Health"])


@router.get("/source-health")
async def get_source_health():
    """获取数据源健康统计"""
    try:
        from app.data.core.interface import DataInterface

        di = DataInterface.get_instance()
        health = await di.get_source_health("CN")
        return ok(data=health)
    except Exception as e:
        return fail(message=f"查询失败: {e}", code=500)


@router.post("/source-health/{source}/{domain}/reset")
async def reset_circuit_breaker(source: str, domain: str):
    """重置指定数据源的熔断器"""
    try:
        from app.data.processor.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker()
        cb.reset(source, domain)
        return ok(message=f"熔断器 {source}/{domain} 已重置")
    except Exception as e:
        return fail(message=f"重置失败: {e}", code=500)
