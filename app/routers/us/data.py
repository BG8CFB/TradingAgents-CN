"""美股数据管理路由 — /api/us/data。"""

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.core.response import ok, fail
from app.data.core.interface import DataInterface

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/us/data", tags=["US Data Management"])

_MARKET = "US"
_DASHBOARD_DOMAINS = [
    "basic_info", "daily_quotes", "daily_indicators",
    "adj_factors", "financial_data", "corporate_actions", "market_quotes", "news",
]
_QUALITY_DOMAINS = [
    "daily_quotes", "daily_indicators", "adj_factors",
    "financial_data", "basic_info", "corporate_actions", "news",
]
_CHECK_DOMAINS = ["daily_quotes", "daily_indicators", "financial_data", "basic_info"]


# ---------------------------------------------------------------------------
# 基础数据
# ---------------------------------------------------------------------------


@router.get("/symbols")
async def get_us_symbols(
    list_status: Optional[str] = Query(None),
):
    di = DataInterface.get_instance()
    return await di.read(_MARKET, "basic_info")


@router.get("/calendar")
async def get_us_calendar(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    di = DataInterface.get_instance()
    return await di.read(_MARKET, "trade_calendar",
                         start_date=start_date, end_date=end_date)


# ---------------------------------------------------------------------------
# 看板
# ---------------------------------------------------------------------------


@router.get("/dashboard")
async def get_dashboard():
    """数据总览看板：域状态 + 源健康 + 覆盖率"""
    health = []
    try:
        di = DataInterface.get_instance()
        health = await di.get_source_health(_MARKET)
    except Exception:
        pass

    domain_stats = {}
    try:
        from app.services.data_dashboard_service import get_domain_stats
        domain_stats = await get_domain_stats(_MARKET, _DASHBOARD_DOMAINS)
    except Exception:
        domain_stats = {d: {"records": 0, "last_updated": None} for d in _DASHBOARD_DOMAINS}

    return ok(data={
        "domain_stats": domain_stats,
        "source_health": health,
        "summary": {
            "total_domains": len(domain_stats),
            "healthy_sources": sum(1 for h in health if isinstance(h, dict) and h.get("circuit_state") == "closed"),
        },
    })


# ---------------------------------------------------------------------------
# 数据源健康
# ---------------------------------------------------------------------------


@router.get("/sources/health")
async def get_us_sources_health():
    di = DataInterface.get_instance()
    return await di.get_source_health(_MARKET)


@router.post("/sources/health/{source}/{domain}/reset")
async def reset_circuit_breaker(source: str, domain: str):
    """重置指定数据源的熔断器"""
    try:
        from app.data.processor.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker()
        cb.reset(source, domain)
        return ok(message=f"熔断器 {source}/{domain} 已重置")
    except Exception as e:
        return fail(message=f"重置失败: {e}", code=500)


# ---------------------------------------------------------------------------
# 数据源配置
# ---------------------------------------------------------------------------


async def _load_priorities_from_db() -> Dict[str, List[str]]:
    di = DataInterface.get_instance()
    domains = [
        "daily_quotes", "daily_indicators", "adj_factors",
        "financial_data", "basic_info", "corporate_actions", "news",
    ]
    priorities: Dict[str, List[str]] = {}
    for domain in domains:
        try:
            config = await di.get_config(_MARKET, domain)
            if config and "sources" in config:
                priorities[domain] = config["sources"]
        except Exception as exc:
            logger.debug("加载域 %s 优先级配置失败: %s", domain, exc)
    return priorities


@router.get("/config/priority")
async def get_us_priority_config():
    """获取所有域的数据源优先级配置"""
    di = DataInterface.get_instance()
    domains = [
        "daily_quotes", "daily_indicators", "adj_factors",
        "financial_data", "basic_info", "corporate_actions", "news",
    ]
    priorities = {}
    for domain in domains:
        try:
            config = await di.get_config(_MARKET, domain)
            if config:
                priorities[domain] = config
        except Exception:
            pass
    return ok(data=priorities)


class PriorityUpdateRequest(BaseModel):
    priority: list[str]


@router.put("/config/priority/{domain}")
async def update_us_priority_config(domain: str, request: PriorityUpdateRequest):
    """更新指定域的数据源优先级（持久化到 MongoDB）"""
    try:
        from app.data.core.registry.capability import CapabilityRegistry
        registry = CapabilityRegistry()

        available = registry.get_available_sources(domain, market=_MARKET)
        if not available:
            return fail(message=f"不支持的数据域: {domain}")

        for source in request.priority:
            level = registry.get_support_level(domain, source, market=_MARKET)
            if level.value == "none":
                return fail(message=f"数据源 {source} 不支持域 {domain}")

        di = DataInterface.get_instance()
        saved = await di.update_config(_MARKET, domain, request.priority)
        if not saved:
            registry.set_user_priority(_MARKET, domain, request.priority)
            return ok(
                message=f"域 {domain} 优先级已更新（仅内存，持久化失败）",
                data={"domain": domain, "priority": request.priority},
            )

        registry.set_user_priority(_MARKET, domain, request.priority)
        return ok(
            message=f"域 {domain} 数据源优先级已更新并持久化",
            data={"domain": domain, "priority": request.priority},
        )
    except Exception as e:
        return fail(message=f"更新失败: {e}", code=500)


@router.get("/source-config")
async def get_source_config():
    """获取数据源配置（能力矩阵 + 用户自定义优先级）"""
    from app.data.core.registry.capability import CapabilityRegistry
    from app.data.config import load_yaml

    default_config = load_yaml("default_priorities.yaml")
    default_priority = default_config.get("US", {})

    registry = CapabilityRegistry()
    matrix = registry.get_matrix_summary(market="US")

    db_priorities = await _load_priorities_from_db()

    priorities = {}
    for d in matrix:
        priorities[d] = db_priorities.get(d) or default_priority.get(d, [])

    return ok(data={
        "capability_matrix": matrix,
        "priorities": priorities,
    })


# ---------------------------------------------------------------------------
# 数据查看
# ---------------------------------------------------------------------------


@router.get("/stock/{symbol}")
async def get_stock_data(
    symbol: str,
    domain: Optional[str] = Query(None, description="数据域，为空返回全部"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """查看单股多域数据"""
    try:
        di = DataInterface.get_instance()
        domains = [domain] if domain else [
            "basic_info", "daily_quotes", "daily_indicators",
            "adj_factors", "financial_data", "corporate_actions", "news",
        ]

        result = {}
        for d in domains:
            try:
                read_result = await di.read(_MARKET, d, symbol=symbol,
                                            start_date=start_date, end_date=end_date)
                data = read_result.get("data", [])
                if isinstance(data, list):
                    total = len(data)
                    start = (page - 1) * page_size
                    items = data[start:start + page_size]
                else:
                    total = 1
                    items = [data] if data else []

                result[d] = {"total": total, "items": items}
            except Exception as exc:
                result[d] = {"total": 0, "items": [], "error": str(exc)}

        return ok(data=result)
    except Exception as e:
        return fail(message=f"查询失败: {e}", code=500)


# ---------------------------------------------------------------------------
# 数据质量
# ---------------------------------------------------------------------------


@router.get("/quality/overview")
async def get_quality_overview():
    """数据质量总览"""
    try:
        from app.services.data_quality_service import get_quality_overview as svc_get_overview
        overview = await svc_get_overview(_MARKET, _QUALITY_DOMAINS)
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
                stats = await check_domain_quality(_MARKET, d)
                results[d] = stats
            except Exception as exc:
                results[d] = {"error": str(exc)}

        return ok(data={"check_id": "inline", "results": results})
    except Exception as e:
        return fail(message=f"检查失败: {e}", code=500)
