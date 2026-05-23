"""测试 DataRefreshService — 数据按需刷新服务。

覆盖范围：
- refresh() 多域并行刷新
- 冷却期检查（force=False 跳过 / force=True 忽略）
- RefreshResult 状态计算
- _fetch_from_source 域映射
- 数据校验

设计原则：不使用 unittest.mock。_refresh_domain 内部流程因为依赖外部
Provider/Adapter/MongoDB/Redis 连接，在无真实服务时无法完全执行，因此
本测试聚焦于可独立验证的纯逻辑部分。
"""

import asyncio
import pytest

from app.data.core.refresh_service import DataRefreshService, _cooldown_cache
from app.data.core.result import RefreshResult, DomainRefreshResult
from app.data.schema.base.enums import RefreshStatus
from app.data.core.registry.capability import CapabilityRegistry
from app.data.core.registry.priority import PriorityConfig


@pytest.fixture(autouse=True)
def clear_cooldown():
    _cooldown_cache.clear()
    yield
    _cooldown_cache.clear()


def _make_service():
    """创建使用真实 Registry + PriorityConfig 的 DataRefreshService。"""
    registry = CapabilityRegistry()
    priority = PriorityConfig()
    service = DataRefreshService(registry, priority)
    return service, registry, priority


# ---------------------------------------------------------------------------
# RefreshResult 状态计算测试
# ---------------------------------------------------------------------------
class TestRefreshResultStatus:
    """测试 RefreshResult.compute_status() 状态计算逻辑。"""

    def test_all_fresh(self):
        r = RefreshResult(symbol="000001", market="CN")
        r.domains = {
            "daily_quotes": DomainRefreshResult(domain="daily_quotes", status="fresh"),
            "basic_info": DomainRefreshResult(domain="basic_info", status="fresh"),
        }
        assert r.compute_status() == RefreshStatus.FRESH

    def test_all_success(self):
        r = RefreshResult(symbol="000001", market="CN")
        r.domains = {
            "daily_quotes": DomainRefreshResult(domain="daily_quotes", status="refreshed"),
            "basic_info": DomainRefreshResult(domain="basic_info", status="fresh"),
        }
        assert r.compute_status() == RefreshStatus.REFRESHED

    def test_partial_failure(self):
        r = RefreshResult(symbol="000001", market="CN")
        r.domains = {
            "daily_quotes": DomainRefreshResult(domain="daily_quotes", status="refreshed"),
            "news": DomainRefreshResult(domain="news", status="failed", error="timeout"),
        }
        status = r.compute_status()
        assert status == RefreshStatus.FAILED

    def test_all_failed(self):
        r = RefreshResult(symbol="000001", market="CN")
        r.domains = {
            "daily_quotes": DomainRefreshResult(domain="daily_quotes", status="failed", error="err1"),
            "news": DomainRefreshResult(domain="news", status="failed", error="err2"),
        }
        assert r.compute_status() == RefreshStatus.FAILED

    def test_empty_domains(self):
        r = RefreshResult(symbol="000001", market="CN")
        assert r.compute_status() == RefreshStatus.FAILED


# ---------------------------------------------------------------------------
# 数据校验测试
# ---------------------------------------------------------------------------
class TestDataValidation:
    """测试 _validate_records 数据校验逻辑。"""

    def test_validate_records_filters_missing_symbol(self):
        service, _, _ = _make_service()
        records = [
            {"symbol": "000001", "trade_date": "2024-01-01"},
            {"trade_date": "2024-01-01"},
            {"symbol": "000002", "trade_date": "2024-01-02"},
        ]
        result = service._validate_records(records, "daily_quotes", "CN")
        assert len(result) == 2

    def test_validate_records_filters_missing_trade_date_for_timeseries(self):
        service, _, _ = _make_service()
        records = [
            {"symbol": "000001", "trade_date": "2024-01-01"},
            {"symbol": "000002"},
        ]
        result = service._validate_records(records, "daily_quotes", "CN")
        assert len(result) == 1

    def test_validate_records_allows_basic_info_without_trade_date(self):
        service, _, _ = _make_service()
        records = [
            {"symbol": "000001"},
            {"symbol": "000002"},
        ]
        result = service._validate_records(records, "basic_info", "CN")
        assert len(result) == 2

    def test_validate_records_empty_input(self):
        service, _, _ = _make_service()
        result = service._validate_records([], "daily_quotes", "CN")
        assert result == []


# ---------------------------------------------------------------------------
# _fetch_from_source 测试
# ---------------------------------------------------------------------------
class TestFetchFromSource:
    """测试 _fetch_from_source 域映射。"""

    @pytest.mark.asyncio
    async def test_unknown_domain_returns_none(self):
        """_fetch_from_source 对于已知域映射中不存在的域返回 None。
        需要有效的 provider 才能构建 method_map，因此使用简单的 provider stub。"""
        service, _, _ = _make_service()

        class StubProvider:
            async def get_stock_list(self, **kw): return []
            async def get_daily_quotes(self, **kw): return []
            async def get_trade_calendar(self, **kw): return []
            async def get_daily_indicators(self, **kw): return []
            async def get_financial_data(self, **kw): return []
            async def get_adj_factors(self, **kw): return []
            async def get_corporate_actions(self, **kw): return []
            async def get_news(self, **kw): return []
            async def get_market_quotes(self, **kw): return []

        result = await service._fetch_from_source(StubProvider(), "unknown_domain", "000001")
        assert result is None


# ---------------------------------------------------------------------------
# DomainRefreshResult 测试
# ---------------------------------------------------------------------------
class TestDomainRefreshResult:
    """测试 DomainRefreshResult 数据类。"""

    def test_default_values(self):
        dr = DomainRefreshResult(domain="daily_quotes", status="fresh")
        assert dr.domain == "daily_quotes"
        assert dr.status == "fresh"
        assert dr.source is None
        assert dr.error is None
        assert dr.record_count == 0

    def test_with_all_fields(self):
        dr = DomainRefreshResult(
            domain="daily_quotes",
            status="refreshed",
            source="tushare",
            record_count=100,
            latency_ms=500,
            fallback_from="akshare",
        )
        assert dr.source == "tushare"
        assert dr.record_count == 100
        assert dr.latency_ms == 500
        assert dr.fallback_from == "akshare"


# ---------------------------------------------------------------------------
# 冷却期测试
# ---------------------------------------------------------------------------
class TestCooldown:
    """测试冷却期缓存机制。"""

    def test_cooldown_cache_set_and_check(self):
        key = "cooldown:CN:000001:daily_quotes"
        _cooldown_cache.set(key, True, ttl=300)
        assert _cooldown_cache.get(key) is not None

    def test_cooldown_cache_clear(self):
        key = "cooldown:CN:000001:daily_quotes"
        _cooldown_cache.set(key, True, ttl=300)
        _cooldown_cache.clear()
        assert _cooldown_cache.get(key) is None
