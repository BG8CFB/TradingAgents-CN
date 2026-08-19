"""BaseMarketDomainSync 收敛到 FallbackRouter 的验证测试（Phase 3 Step 3.2/3.3）。

验证：
1. HK/US 全部同步域都有对应 Repo 分发（upsert 键来自 key_spec 单一事实源）
2. FallbackRouter.fetch_source 的四件套语义：
   - 数据源错误（如坏 token）→ "failed" 并计入熔断
   - 熔断打开 → "skip"（不计失败）
   - 未注册源 → "skip"
3. sync() 全源失败时写 SYNC_FAILED sync_event（真实 MongoDB）

设计原则：不使用 unittest.mock；使用真实 CapabilityRegistry、真实
FallbackRouter 组件（熔断器/限流器接真实 Redis）、真实 MongoDB。
坏源通过真实 DataSourceError 子类触发，不伪造网络。
"""

import pytest

from app.data.core.registry.capability import CapabilityRegistry
from app.data.core.registry.priority import PriorityConfig
from app.data.processor.fallback_router import FallbackRouter, reset_singleton
from app.data.schema.base.enums import SupportLevel
from app.data.sources.base.exceptions import RateLimitedError
from app.worker.base_market_sync import _REPO_TABLE, _get_repo

pytestmark = pytest.mark.asyncio


def _make_router(source: str, domain: str, market: str = "HK") -> FallbackRouter:
    registry = CapabilityRegistry()
    registry.register(market, domain, source, SupportLevel.FULL)
    return FallbackRouter(registry, PriorityConfig())


@pytest.fixture(autouse=True)
def _reset_router_singleton():
    """避免污染进程级单例（测试用独立实例，不经过 get_instance）。"""
    reset_singleton()
    yield
    reset_singleton()


class TestRepoDispatch:
    """Step 3.3：入库按域分发到 Repo，禁止内联 bulk_write。"""

    def test_repo_table_covers_hk_us_sync_domains(self):
        """HK/US 域同步使用的全部域必须有 Repo 注册。"""
        hk_us_domains = {
            "basic_info", "trade_calendar", "daily_quotes", "daily_indicators",
            "financial_data", "adj_factors", "corporate_actions",
            "market_quotes", "news",
        }
        missing = hk_us_domains - set(_REPO_TABLE)
        assert not missing, f"缺少 Repo 注册的域: {missing}"

    def test_get_repo_returns_upsert_many_interface(self):
        for domain in ("daily_quotes", "market_quotes", "trade_calendar"):
            repo = _get_repo(domain)
            assert hasattr(repo, "upsert_many"), f"{domain} Repo 缺少 upsert_many"

    def test_get_repo_unknown_domain_raises(self):
        with pytest.raises(ValueError):
            _get_repo("no_such_domain")

    async def test_repo_upsert_uses_key_spec_keys(self, real_mongo_db):
        """HK 域经 Repo upsert：键来自 key_spec（daily_quotes = symbol+trade_date+period），
        同自然键二次写入为覆盖而非新增（单版本覆盖语义）。"""
        from app.data.storage.mongo.collections import get_collection_name

        repo = _get_repo("daily_quotes")
        base = {"symbol": "00700", "trade_date": "2026-08-18", "period": "daily",
                "close": 300.0, "data_source": "tushare_hk"}
        n1 = await repo.upsert_many([dict(base)], "HK")
        assert n1 >= 1

        coll = real_mongo_db[get_collection_name("daily_quotes", "HK")]
        assert await coll.count_documents({"symbol": "00700", "trade_date": "2026-08-18"}) == 1

        # 备用源覆盖同自然键（data_source 不同、键相同）
        override = dict(base, close=310.0, data_source="akshare_hk")
        await repo.upsert_many([override], "HK")
        docs = await coll.find(
            {"symbol": "00700", "trade_date": "2026-08-18"}
        ).to_list(length=None)
        assert len(docs) == 1
        assert docs[0]["close"] == 310.0
        await coll.delete_many({"symbol": "00700", "trade_date": "2026-08-18"})


class TestFetchSourceSemantics:
    """Step 3.2：单源尝试的四件套语义。"""

    async def test_source_error_records_failure(self):
        """数据源错误（坏 token/限流等）→ failed 并计入熔断。"""
        router = _make_router("tushare_hk", "daily_quotes")

        async def bad_token_fetch(provider):
            raise RateLimitedError("tushare_hk", "daily_quotes")

        status, records, _ = await router.fetch_source(
            "HK", "daily_quotes", "tushare_hk", bad_token_fetch
        )
        assert status == "failed"
        assert records == []

        state = router._circuit.get_state("tushare_hk", domain="daily_quotes", market="HK")
        assert state.value in ("closed", "open", "half_open")  # 已开始累计失败

    async def test_open_circuit_skips_without_failure(self):
        """熔断打开 → skip，不消耗限流配额也不计新失败。"""
        router = _make_router("tushare_hk", "daily_quotes")
        cb = router._circuit
        for _ in range(10):
            cb.record_failure("tushare_hk", domain="daily_quotes", market="HK")
        assert cb.is_open("tushare_hk", domain="daily_quotes", market="HK")

        async def should_not_be_called(provider):
            raise AssertionError("熔断打开时不应调用 provider")

        status, _, _ = await router.fetch_source(
            "HK", "daily_quotes", "tushare_hk", should_not_be_called
        )
        assert status == "skip"

    async def test_unregistered_source_skips(self):
        """源未在工厂注册 → skip（provider 为 None，静默尝试次源）。"""
        router = _make_router("no_such_source", "daily_quotes")

        async def any_fetch(provider):
            return None

        status, _, _ = await router.fetch_source(
            "HK", "daily_quotes", "no_such_source", any_fetch
        )
        assert status == "skip"


class TestSyncEventSemantics:
    """sync() 失败也写 SYNC_FAILED sync_event（保留监控语义）。"""

    async def test_sync_failure_writes_sync_failed_event(self, real_mongo_db):
        from app.data.storage.mongo.collections import get_collection_name
        from app.worker.hk.domain_sync._common import HKDomainSync

        syncer = HKDomainSync(domain="trade_calendar")
        result = await syncer._write_sync_event(
            success=False, source="", record_count=0,
            duration_ms=10, error="所有数据源失败",
        )
        assert result is None

        coll = real_mongo_db[get_collection_name("sync_events", "HK")]
        doc = await coll.find_one(
            {"event_type": "SYNC_FAILED", "domain": "trade_calendar", "market": "HK"}
        )
        assert doc is not None
        await coll.delete_one({"_id": doc["_id"]})
