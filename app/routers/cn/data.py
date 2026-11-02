"""A 股数据管理路由 — /api/cn/data。"""

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Query, Depends
from pydantic import BaseModel

from app.core.response import ok, fail
from app.data.core.interface import DataInterface
from app.data.core.registry.capability import CapabilityRegistry
from app.routers.auth_db import get_current_user, require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cn/data", tags=["CN Data Management"])

_MARKET = "CN"


def _all_domains() -> List[str]:
    """从 CapabilityRegistry 动态获取当前市场的全部数据域。"""
    return CapabilityRegistry().get_domains(_MARKET)


# ---------------------------------------------------------------------------
# 看板
# ---------------------------------------------------------------------------


@router.get("/dashboard")
async def get_dashboard(user: dict = Depends(get_current_user)):
    """数据总览看板：域健康（三支柱判定）+ 源健康 + 市场总览"""
    from app.services.data_dashboard_service import get_dashboard_payload

    return ok(data=await get_dashboard_payload(_MARKET))


# ---------------------------------------------------------------------------
# 数据源健康
# ---------------------------------------------------------------------------


@router.get("/sources/health")
async def get_cn_sources_health(user: dict = Depends(get_current_user)):
    di = DataInterface.get_instance()
    return await di.get_source_health(_MARKET)


@router.post("/sources/health/{data_source}/{domain}/reset")
async def reset_circuit_breaker(
    data_source: str,
    domain: str,
    user: dict = Depends(require_admin),
):
    """重置指定数据源的熔断器（需管理员权限）"""
    try:
        di = DataInterface.get_instance()
        await di.reset_source_circuit(_MARKET, data_source, domain)
        return ok(message=f"熔断器 {data_source}/{domain} 已重置")
    except Exception as e:
        return fail(message=f"重置失败: {e}", code=500)


# ---------------------------------------------------------------------------
# 数据源配置
# ---------------------------------------------------------------------------


async def _load_priorities_from_db() -> Dict[str, List[str]]:
    """从 MongoDB 加载用户配置的优先级"""
    di = DataInterface.get_instance()
    domains = _all_domains()
    priorities: Dict[str, List[str]] = {}
    for domain in domains:
        try:
            config = await di.get_config(_MARKET, domain)
            if config and "sources" in config:
                priorities[domain] = config["sources"]
        except Exception as exc:
            logger.debug("加载域 %s 优先级配置失败: %s", domain, exc)
    return priorities


class PriorityUpdateRequest(BaseModel):
    priority: list[str]


@router.put("/config/priority/{domain}")
async def update_cn_priority_config(
    domain: str,
    request: PriorityUpdateRequest,
    user: dict = Depends(require_admin),
):
    """更新指定域的数据源优先级（持久化到 MongoDB，需管理员权限）"""
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
            # 持久化失败必须如实报错：旧分支写的「仅内存生效」缓存实际无任何
            # 读取方（写死状态），更新会被静默丢弃（组 2 治理，2026-11-02）
            return fail(message=f"域 {domain} 优先级持久化失败，未生效，请重试", code=500)

        return ok(
            message=f"域 {domain} 数据源优先级已更新并持久化",
            data={"domain": domain, "priority": request.priority},
        )
    except Exception as e:
        return fail(message=f"更新失败: {e}", code=500)


@router.get("/source-config")
async def get_source_config(user: dict = Depends(get_current_user)):
    """获取数据源配置（能力矩阵 + 用户自定义优先级）"""
    from app.data.config import load_yaml

    default_config = load_yaml("default_priorities.yaml")
    default_priority = default_config.get("CN", {})

    registry = CapabilityRegistry()
    matrix = registry.get_matrix_summary(market="CN")

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
    user: dict = Depends(get_current_user),
):
    """查看单股多域数据（抽样校验：每域按最新记录优先分页）"""
    try:
        from app.routers.cn.data_viewer import paginate_domain_items

        di = DataInterface.get_instance()
        domains = [domain] if domain else _all_domains()

        result = {}
        for d in domains:
            try:
                read_result = await di.read(_MARKET, d, symbol=symbol,
                                            start_date=start_date, end_date=end_date)
                data = read_result.get("data", [])
                result[d] = paginate_domain_items(d, data, page, page_size)
            except Exception as exc:
                result[d] = {"total": 0, "items": [], "error": str(exc)}

        return ok(data=result)
    except Exception as e:
        return fail(message=f"查询失败: {e}", code=500)


# ---------------------------------------------------------------------------
# 数据质量
# ---------------------------------------------------------------------------


@router.get("/quality/overview")
async def get_quality_overview(user: dict = Depends(get_current_user)):
    """数据质量总览 — 各域记录数、完整率、最新日期"""
    try:
        from app.services.data_quality_service import get_quality_overview as svc_get_overview
        overview = await svc_get_overview(_MARKET, _all_domains())
        return ok(data=overview)
    except Exception as e:
        return fail(message=f"查询失败: {e}", code=500)


@router.post("/quality/check")
async def trigger_quality_check(
    domain: Optional[str] = Query(None, description="指定域，为空检查全部"),
    user: dict = Depends(require_admin),
):
    """触发数据质量检查（需管理员权限）"""
    try:
        from app.services.data_quality_service import check_domain_quality
        results = {}
        domains = [domain] if domain else _all_domains()
        for d in domains:
            try:
                stats = await check_domain_quality(_MARKET, d)
                results[d] = stats
            except Exception as exc:
                results[d] = {"error": str(exc)}

        return ok(data={"check_id": "inline", "results": results})
    except Exception as e:
        return fail(message=f"检查失败: {e}", code=500)
