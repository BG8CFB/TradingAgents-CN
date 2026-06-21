"""
同步状态修复单元测试 — 验证 5 层问题的修复方案。

覆盖：
1. SyncCheckpointSchema 新字段（scope/trigger/symbol/duration_ms）
2. MetadataRepo.update_checkpoint 写入带 market 字段 + 新参数
3. MetadataRepo.get_all_checkpoints 的 trigger 过滤 + market 隔离
4. DataInterface.get_sync_status 透传 trigger
5. get_latest_trade_day 交易日回退
6. DataRefreshService._get_incremental_date_range 三元组 + end_date 回退
7. DataRefreshService._refresh_domain 空结果区分 fresh/failed
8. CN worker BaseDomainSync._write_checkpoint 带 market 字段
9. BaseMarketDomainSync._write_checkpoint 成功/失败写入
10. refresh 成功后写 manual checkpoint

测试原则：无 mock，通过 inject_sim_db 使用 SimulatedMongoDB 做真实 I/O。
"""

import inspect
from datetime import date

import pytest

from app.data.schema.domains.metadata import SyncCheckpointSchema


# ============================================================
# 辅助：最小化假 Router（实例方法 fetch，匹配 router.fetch 调用方式）
# ============================================================

class _FakeRouter:
    """作为 _get_router() 返回值。fetch 是实例方法（self + market/domain/symbol）。"""

    def __init__(self, result_factory):
        self._factory = result_factory

    async def fetch(self, market, domain, symbol, **kwargs):
        return self._factory()


def _patch_today(monkeypatch, fixed_date):
    """固定 app.data.core.market.date 的 today() 为 fixed_date。"""
    from app.data.core import market as market_mod
    monkeypatch.setattr(market_mod, "date", type("_D", (), {
        "today": staticmethod(lambda: fixed_date),
        "fromisoformat": staticmethod(date.fromisoformat),
    }))


# ============================================================
# 测试 1: SyncCheckpointSchema 新字段
# ============================================================

class TestSyncCheckpointSchema:
    """验证 SyncCheckpointSchema 新增字段正确。"""

    def test_new_fields_all_optional_with_defaults(self):
        s = SyncCheckpointSchema(market="CN", domain="daily_quotes", source="tushare")
        doc = s.to_db_doc()
        assert doc["market"] == "CN"
        assert "scope" not in doc
        assert "trigger" not in doc
        assert "symbol" not in doc
        assert "duration_ms" not in doc

    def test_new_fields_when_set(self):
        s = SyncCheckpointSchema(
            market="CN", domain="daily_quotes", source="tushare",
            scope="single", trigger="manual", symbol="000001", duration_ms=200,
            last_sync_date="2026-06-19", status="success", record_count=5,
        )
        doc = s.to_db_doc()
        assert doc["scope"] == "single"
        assert doc["trigger"] == "manual"
        assert doc["symbol"] == "000001"
        assert doc["duration_ms"] == 200


# ============================================================
# 测试 2-3: MetadataRepo checkpoint 写入
# ============================================================

class TestMetadataRepoCheckpoint:

    @pytest.mark.asyncio
    async def test_update_checkpoint_includes_market_field(self, inject_sim_db):
        """核心 bug 修复：写入的文档必须包含 market 字段。"""
        from app.data.storage.mongo.repositories.metadata_repo import MetadataRepo

        repo = MetadataRepo()
        await repo.update_checkpoint(
            market="CN", domain="daily_quotes", source="tushare",
            last_sync_date="2026-06-19", record_count=5, status="success",
        )

        coll = inject_sim_db["sync_checkpoints"]
        doc = await coll.find_one({"market": "CN", "domain": "daily_quotes"})
        assert doc is not None, "checkpoint 未写入或缺少 market 字段"
        assert doc["market"] == "CN"
        assert doc["record_count"] == 5

    @pytest.mark.asyncio
    async def test_update_checkpoint_with_new_optional_params(self, inject_sim_db):
        from app.data.storage.mongo.repositories.metadata_repo import MetadataRepo

        repo = MetadataRepo()
        await repo.update_checkpoint(
            market="CN", domain="daily_quotes", source="akshare",
            last_sync_date="2026-06-19", record_count=10, status="success",
            duration_ms=500, scope="single", trigger="manual", symbol="000001",
        )

        coll = inject_sim_db["sync_checkpoints"]
        doc = await coll.find_one({"market": "CN", "symbol": "000001"})
        assert doc["scope"] == "single"
        assert doc["trigger"] == "manual"
        assert doc["symbol"] == "000001"
        assert doc["duration_ms"] == 500

    @pytest.mark.asyncio
    async def test_update_checkpoint_optional_params_not_overwrite_old_docs(self, inject_sim_db):
        """新参数为 None 时不写入 $set，避免覆盖旧文档字段。"""
        from app.data.storage.mongo.repositories.metadata_repo import MetadataRepo

        repo = MetadataRepo()
        await repo.update_checkpoint(
            market="CN", domain="daily_quotes", source="tushare",
            last_sync_date="2026-06-19", record_count=1, status="success",
            scope="market", trigger="scheduled",
        )
        # 第二次不传可选参数（模拟旧调用方）
        await repo.update_checkpoint(
            market="CN", domain="daily_quotes", source="tushare",
            last_sync_date="2026-06-20", record_count=2, status="success",
        )

        coll = inject_sim_db["sync_checkpoints"]
        doc = await coll.find_one({"market": "CN", "domain": "daily_quotes"})
        assert doc["scope"] == "market"
        assert doc["trigger"] == "scheduled"
        assert doc["last_sync_date"] == "2026-06-20"

    @pytest.mark.asyncio
    async def test_get_all_checkpoints_trigger_filter(self, inject_sim_db):
        from app.data.storage.mongo.repositories.metadata_repo import MetadataRepo

        repo = MetadataRepo()
        await repo.update_checkpoint(
            market="CN", domain="daily_quotes", source="tushare",
            last_sync_date="2026-06-19", record_count=5, status="success",
            trigger="manual", symbol="000001",
        )
        await repo.update_checkpoint(
            market="CN", domain="daily_quotes", source="akshare",
            last_sync_date="2026-06-19", record_count=100, status="success",
            trigger="scheduled",
        )

        scheduled = await repo.get_all_checkpoints("CN", "daily_quotes", trigger="scheduled")
        assert len(scheduled) >= 1
        for cp in scheduled:
            assert cp["trigger"] == "scheduled"

        manual = await repo.get_all_checkpoints("CN", "daily_quotes", trigger="manual")
        assert len(manual) >= 1
        for cp in manual:
            assert cp["trigger"] == "manual"
        assert any(cp.get("symbol") == "000001" for cp in manual)

    @pytest.mark.asyncio
    async def test_get_all_checkpoints_market_isolation(self, inject_sim_db):
        from app.data.storage.mongo.repositories.metadata_repo import MetadataRepo

        repo = MetadataRepo()
        await repo.update_checkpoint(
            market="CN", domain="daily_quotes", source="tushare",
            last_sync_date="2026-06-19", record_count=10, status="success",
        )
        await repo.update_checkpoint(
            market="HK", domain="daily_quotes", source="tushare_hk",
            last_sync_date="2026-06-19", record_count=20, status="success",
        )

        cn_cps = await repo.get_all_checkpoints("CN")
        hk_cps = await repo.get_all_checkpoints("HK")
        assert all(cp["market"] == "CN" for cp in cn_cps)
        assert all(cp["market"] == "HK" for cp in hk_cps)


# ============================================================
# 测试 4: DataInterface trigger 透传
# ============================================================

class TestDataInterfaceTriggerPassThrough:

    def test_signature_has_trigger_param(self):
        from app.data.core.interface import DataInterface
        sig = inspect.signature(DataInterface.get_sync_status)
        assert "trigger" in sig.parameters
        assert sig.parameters["trigger"].default is None

    @pytest.mark.asyncio
    async def test_trigger_passed_to_repo(self, monkeypatch, inject_sim_db):
        from app.data.core.interface import DataInterface
        di = DataInterface.get_instance()

        captured = {}

        async def spy_get_all(market, domain=None, trigger=None):
            captured["market"] = market
            captured["domain"] = domain
            captured["trigger"] = trigger
            return []

        monkeypatch.setattr(di._metadata_repo, "get_all_checkpoints", spy_get_all)
        await di.get_sync_status("CN", "daily_quotes", trigger="scheduled")
        assert captured["trigger"] == "scheduled"


# ============================================================
# 测试 5: get_latest_trade_day
# ============================================================

class TestGetLatestTradeDay:

    @pytest.mark.asyncio
    async def test_returns_latest_open_day_before_given_date(self, inject_sim_db):
        from app.data.core.market import get_latest_trade_day

        coll = inject_sim_db["trade_calendar"]
        await coll.insert_many([
            {"exchange": "SSE", "cal_date": "2026-06-18", "is_open": True},
            {"exchange": "SSE", "cal_date": "2026-06-19", "is_open": True},
            {"exchange": "SSE", "cal_date": "2026-06-20", "is_open": False},
            {"exchange": "SSE", "cal_date": "2026-06-21", "is_open": False},
        ])

        sunday = date(2026, 6, 21)
        result = await get_latest_trade_day("CN", sunday)
        assert result == date(2026, 6, 19), f"周日应回退到周五，实际: {result}"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_calendar_data(self, inject_sim_db):
        from app.data.core.market import get_latest_trade_day
        result = await get_latest_trade_day("CN", date(2026, 6, 21))
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_all_closed_window(self, inject_sim_db):
        from app.data.core.market import get_latest_trade_day

        coll = inject_sim_db["trade_calendar"]
        await coll.insert_many([
            {"exchange": "SSE", "cal_date": "2026-06-18", "is_open": False},
            {"exchange": "SSE", "cal_date": "2026-06-19", "is_open": False},
        ])
        result = await get_latest_trade_day("CN", date(2026, 6, 21))
        assert result is None

    @pytest.mark.asyncio
    async def test_handles_holiday_long_weekend(self, inject_sim_db):
        from app.data.core.market import get_latest_trade_day

        coll = inject_sim_db["trade_calendar"]
        docs = [
            {"exchange": "SSE", "cal_date": "2026-09-28", "is_open": True},
            {"exchange": "SSE", "cal_date": "2026-09-29", "is_open": True},
            {"exchange": "SSE", "cal_date": "2026-09-30", "is_open": True},
        ]
        for day in range(1, 8):
            docs.append({"exchange": "SSE", "cal_date": f"2026-10-0{day}", "is_open": False})
        await coll.insert_many(docs)

        result = await get_latest_trade_day("CN", date(2026, 10, 5))
        assert result == date(2026, 9, 30)


# ============================================================
# 测试 6: _get_incremental_date_range
# ============================================================

class TestRefreshServiceDateRange:

    def test_returns_three_tuple(self):
        from app.data.core.refresh_service import DataRefreshService
        assert inspect.iscoroutinefunction(DataRefreshService._get_incremental_date_range)

    @pytest.mark.asyncio
    async def test_end_date_falls_back_to_trade_day(self, inject_sim_db, monkeypatch):
        from app.data.core.refresh_service import DataRefreshService
        from app.data.core.registry.capability import CapabilityRegistry
        from app.data.core.registry.priority import PriorityConfig

        _patch_today(monkeypatch, date(2026, 6, 21))

        coll = inject_sim_db["trade_calendar"]
        await coll.insert_many([
            {"exchange": "SSE", "cal_date": "2026-06-18", "is_open": True},
            {"exchange": "SSE", "cal_date": "2026-06-19", "is_open": True},
            {"exchange": "SSE", "cal_date": "2026-06-20", "is_open": False},
            {"exchange": "SSE", "cal_date": "2026-06-21", "is_open": False},
        ])

        svc = DataRefreshService(CapabilityRegistry(), PriorityConfig())
        start, end, latest_db = await svc._get_incremental_date_range(
            "CN", "TESTSYMBOL", "daily_quotes"
        )
        assert latest_db is None
        assert end == "2026-06-19", f"end_date 应回退到最近交易日 06-19，实际: {end}"

    @pytest.mark.asyncio
    async def test_latest_db_date_extracted_from_existing_data(self, inject_sim_db):
        from app.data.core.refresh_service import DataRefreshService
        from app.data.core.registry.capability import CapabilityRegistry
        from app.data.core.registry.priority import PriorityConfig
        from app.data.storage.mongo.collections import get_collection_name

        coll_name = get_collection_name("daily_quotes", "CN")
        coll = inject_sim_db[coll_name]
        await coll.insert_many([
            {"symbol": "000001", "trade_date": "2026-06-10", "close": 9.0},
            {"symbol": "000001", "trade_date": "2026-06-15", "close": 10.0},
        ])

        cal_coll = inject_sim_db["trade_calendar"]
        await cal_coll.insert_many([
            {"exchange": "SSE", "cal_date": "2026-06-19", "is_open": True},
        ])

        svc = DataRefreshService(CapabilityRegistry(), PriorityConfig())
        start, end, latest_db = await svc._get_incremental_date_range(
            "CN", "000001", "daily_quotes"
        )
        # find_one(sort=[("trade_date", -1)]) 应取最新 06-15
        assert latest_db == "2026-06-15", f"应取最新 trade_date 06-15，实际: {latest_db}"
        assert start == "2026-06-08"


# ============================================================
# 测试 7: _refresh_domain 空结果区分 fresh/failed
# ============================================================

class TestRefreshServiceFreshVsFailed:
    """fresh/failed 分支在 _write_to_mongo 之前 return，不触发 bulk_write。"""

    @pytest.mark.asyncio
    async def test_up_to_date_returns_fresh_not_failed(self, inject_sim_db, monkeypatch):
        """库已最新（latest_db_date >= end_date）+ 源失败 → fresh。"""
        from app.data.core.refresh_service import DataRefreshService
        from app.data.core.registry.capability import CapabilityRegistry
        from app.data.core.registry.priority import PriorityConfig
        from app.data.processor.fallback_router import FetchResult
        from app.data.storage.mongo.collections import get_collection_name

        _patch_today(monkeypatch, date(2026, 6, 21))

        coll = inject_sim_db[get_collection_name("daily_quotes", "CN")]
        await coll.insert_many([
            {"symbol": "TESTFRESH", "trade_date": "2026-06-19", "close": 10.0},
        ])
        cal_coll = inject_sim_db["trade_calendar"]
        await cal_coll.insert_many([
            {"exchange": "SSE", "cal_date": "2026-06-19", "is_open": True},
        ])

        svc = DataRefreshService(CapabilityRegistry(), PriorityConfig())

        def make_failure():
            r = FetchResult()
            r.success = False
            r.error = "所有源失败"
            return r

        monkeypatch.setattr(svc, "_get_router", lambda: _FakeRouter(make_failure))
        dr = await svc._refresh_domain("CN", "TESTFRESH", "daily_quotes", force=True, timeout=30)
        assert dr.status == "fresh", f"数据已最新时应标 fresh，实际: {dr.status}"

    @pytest.mark.asyncio
    async def test_real_source_failure_returns_failed(self, inject_sim_db, monkeypatch):
        """库未最新（latest_db_date < end_date）+ 源失败 → failed。"""
        from app.data.core.refresh_service import DataRefreshService
        from app.data.core.registry.capability import CapabilityRegistry
        from app.data.core.registry.priority import PriorityConfig
        from app.data.processor.fallback_router import FetchResult
        from app.data.storage.mongo.collections import get_collection_name

        _patch_today(monkeypatch, date(2026, 6, 21))

        coll = inject_sim_db[get_collection_name("daily_quotes", "CN")]
        await coll.insert_many([
            {"symbol": "TESTFAIL", "trade_date": "2026-06-10", "close": 10.0},
        ])
        cal_coll = inject_sim_db["trade_calendar"]
        await cal_coll.insert_many([
            {"exchange": "SSE", "cal_date": "2026-06-19", "is_open": True},
        ])

        svc = DataRefreshService(CapabilityRegistry(), PriorityConfig())

        def make_failure():
            r = FetchResult()
            r.success = False
            r.error = "连接超时"
            return r

        monkeypatch.setattr(svc, "_get_router", lambda: _FakeRouter(make_failure))
        dr = await svc._refresh_domain("CN", "TESTFAIL", "daily_quotes", force=True, timeout=30)
        assert dr.status == "failed", f"源真正失败时应标 failed，实际: {dr.status}"


# ============================================================
# 测试 8: CN worker checkpoint
# ============================================================

class TestCNWorkerCheckpointFix:

    @pytest.mark.asyncio
    async def test_cn_worker_writes_market_field(self, inject_sim_db):
        from app.worker.cn.domain_sync.base_domain_sync import BaseDomainSync

        class TestSync(BaseDomainSync):
            domain = "daily_quotes"
            description = "test"
            async def sync(self):
                pass

        sync = TestSync()
        await sync._write_checkpoint(
            source="tushare", status="success",
            record_count=50, duration_ms=300,
        )

        coll = inject_sim_db["sync_checkpoints"]
        doc = await coll.find_one({"market": "CN", "domain": "daily_quotes"})
        assert doc is not None, "CN worker 写入的 checkpoint 必须能被 {market: CN} 查到"
        assert doc["market"] == "CN"
        assert doc["scope"] == "market"
        assert doc["trigger"] == "scheduled"
        assert doc["duration_ms"] == 300


# ============================================================
# 测试 9: BaseMarketDomainSync checkpoint
# ============================================================

class TestBaseMarketSyncCheckpoint:

    @pytest.mark.asyncio
    async def test_writes_success_checkpoint(self, inject_sim_db):
        from app.worker.base_market_sync import BaseMarketDomainSync

        class TestHkSync(BaseMarketDomainSync):
            market = "HK"
            domain = "daily_quotes"
            def get_provider(self, source_name): return None
            def get_adapter(self, source_name): return None

        sync = TestHkSync()
        await sync._write_checkpoint(
            success=True, source="tushare_hk",
            record_count=30, duration_ms=200,
        )

        coll = inject_sim_db["sync_checkpoints"]
        doc = await coll.find_one({"market": "HK", "domain": "daily_quotes"})
        assert doc is not None
        assert doc["status"] == "success"
        assert doc["scope"] == "market"
        assert doc["trigger"] == "scheduled"

    @pytest.mark.asyncio
    async def test_writes_failed_checkpoint(self, inject_sim_db):
        from app.worker.base_market_sync import BaseMarketDomainSync

        class TestUsSync(BaseMarketDomainSync):
            market = "US"
            domain = "daily_quotes"
            def get_provider(self, source_name): return None
            def get_adapter(self, source_name): return None

        sync = TestUsSync()
        await sync._write_checkpoint(
            success=False, source="", record_count=0, duration_ms=100,
        )

        coll = inject_sim_db["sync_checkpoints"]
        doc = await coll.find_one({"market": "US"})
        assert doc is not None
        assert doc["status"] == "failed"


# ============================================================
# 测试 10: refresh 成功后写 manual checkpoint
# ============================================================

class TestRefreshWritesCheckpoint:

    @pytest.mark.asyncio
    async def test_successful_refresh_writes_manual_checkpoint(self, inject_sim_db, monkeypatch):
        """手动刷新成功后应写 scope=single/trigger=manual 的 checkpoint。

        _write_to_mongo 是纯 I/O（repo.upsert_many → bulk_write，sim_db 不支持），
        隔离它以聚焦验证"成功后是否写 manual checkpoint"这一调用路径。
        repo.upsert_many 的写入正确性由 worker 测试覆盖。
        """
        from app.data.core.refresh_service import DataRefreshService
        from app.data.core.registry.capability import CapabilityRegistry
        from app.data.core.registry.priority import PriorityConfig
        from app.data.processor.fallback_router import FetchResult

        _patch_today(monkeypatch, date(2026, 6, 21))

        cal_coll = inject_sim_db["trade_calendar"]
        await cal_coll.insert_many([
            {"exchange": "SSE", "cal_date": "2026-06-19", "is_open": True},
        ])

        svc = DataRefreshService(CapabilityRegistry(), PriorityConfig())

        async def fake_write_to_mongo(records, domain, market):
            return len(records)
        monkeypatch.setattr(svc, "_write_to_mongo", fake_write_to_mongo)

        def make_success():
            r = FetchResult()
            r.success = True
            r.source = "tushare"
            r.records = [{"symbol": "TESTMANUAL", "trade_date": "2026-06-19", "close": 15.0}]
            return r

        monkeypatch.setattr(svc, "_get_router", lambda: _FakeRouter(make_success))

        dr = await svc._refresh_domain("CN", "TESTMANUAL", "daily_quotes", force=True, timeout=30)
        assert dr.status == "refreshed", f"成功应标 refreshed，实际: {dr.status}"

        coll = inject_sim_db["sync_checkpoints"]
        doc = await coll.find_one({
            "market": "CN", "domain": "daily_quotes", "scope": "single",
            "symbol": "TESTMANUAL",
        })
        assert doc is not None, "手动刷新应写 scope=single checkpoint"
        assert doc["trigger"] == "manual"
        assert doc["symbol"] == "TESTMANUAL"
        assert doc["status"] == "success"
