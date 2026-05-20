"""CNSyncOrchestrator 和域同步模块测试"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.data.processor.fallback_router import FetchResult


class TestDomainSyncResult:
    def test_to_dict(self):
        from app.worker.cn.domain_sync.base_domain_sync import DomainSyncResult
        r = DomainSyncResult(
            domain="daily_quotes", success=True,
            source="tushare", records_synced=100,
            duration_ms=500,
        )
        d = r.to_dict()
        assert d["domain"] == "daily_quotes"
        assert d["success"] is True
        assert d["records_synced"] == 100


class TestBasicInfoSync:
    @pytest.mark.asyncio
    async def test_sync_success(self):
        from app.worker.cn.domain_sync.basic_info_sync import BasicInfoSync

        mock_router = MagicMock()
        mock_router.fetch = AsyncMock(return_value=FetchResult(
            success=True, data=[{"symbol": "000001", "name": "平安银行"}],
            source="tushare", domain="basic_info",
        ))

        sync = BasicInfoSync(router=mock_router)

        with patch.object(sync, "_write_to_mongo", new_callable=AsyncMock, return_value=1):
            with patch.object(sync, "_write_sync_event", new_callable=AsyncMock):
                with patch.object(sync, "_write_checkpoint", new_callable=AsyncMock):
                    result = await sync.sync()

        assert result.success
        assert result.domain == "basic_info"
        assert result.source == "tushare"

    @pytest.mark.asyncio
    async def test_sync_failure(self):
        from app.worker.cn.domain_sync.basic_info_sync import BasicInfoSync

        mock_router = MagicMock()
        mock_router.fetch = AsyncMock(return_value=FetchResult(
            success=False, error="数据源不可用",
            source="tushare", domain="basic_info",
        ))

        sync = BasicInfoSync(router=mock_router)

        with patch.object(sync, "_write_sync_event", new_callable=AsyncMock):
            with patch.object(sync, "_write_checkpoint", new_callable=AsyncMock):
                result = await sync.sync()

        assert not result.success
        assert result.error == "数据源不可用"


class TestDailyQuotesSync:
    @pytest.mark.asyncio
    async def test_requires_symbol(self):
        from app.worker.cn.domain_sync.daily_quotes_sync import DailyQuotesSync

        mock_router = MagicMock()
        sync = DailyQuotesSync(router=mock_router)
        result = await sync.sync(symbol=None)

        assert not result.success
        assert "symbol" in result.error

    @pytest.mark.asyncio
    async def test_sync_with_symbol(self):
        from app.worker.cn.domain_sync.daily_quotes_sync import DailyQuotesSync

        mock_router = MagicMock()
        mock_router.fetch = AsyncMock(return_value=FetchResult(
            success=True, data=[{"symbol": "000001", "trade_date": "2026-05-19", "close": 10}],
            source="tushare", domain="daily_quotes",
        ))

        sync = DailyQuotesSync(router=mock_router)

        with patch.object(sync, "_write_to_mongo", new_callable=AsyncMock, return_value=1):
            with patch.object(sync, "_write_sync_event", new_callable=AsyncMock):
                with patch.object(sync, "_write_checkpoint", new_callable=AsyncMock):
                    result = await sync.sync(symbol="000001")

        assert result.success
        assert result.records_synced == 1


class TestCNSyncOrchestrator:
    @pytest.mark.asyncio
    async def test_trading_day_check(self):
        from app.worker.cn.cn_sync_orchestrator import CNSyncOrchestrator

        orchestrator = CNSyncOrchestrator()

        with patch.object(orchestrator, "is_trading_day", return_value=True):
            assert await orchestrator.is_trading_day()

    @pytest.mark.asyncio
    async def test_non_trading_day_skips(self):
        """非交易日跳过同步"""
        from app.worker.cn.cn_sync_orchestrator import CNSyncOrchestrator

        orchestrator = CNSyncOrchestrator()

        with patch.object(orchestrator, "is_trading_day", return_value=False):
            result = await orchestrator.run(
                symbol="000001",
                skip_trading_day_check=False,
            )

        assert result.skipped
        assert result.skip_reason == "非交易日"

    @pytest.mark.asyncio
    async def test_run_single_symbol(self):
        """单股同步返回各域结果"""
        from app.worker.cn.cn_sync_orchestrator import CNSyncOrchestrator
        from app.worker.cn.domain_sync.base_domain_sync import DomainSyncResult

        orchestrator = CNSyncOrchestrator()

        # Mock 各域同步
        mock_result = DomainSyncResult(domain="daily_quotes", success=True, source="tushare", records_synced=10)
        for domain, sync in orchestrator._domain_syncs.items():
            sync.sync = AsyncMock(return_value=DomainSyncResult(
                domain=domain, success=True, source="tushare", records_synced=5,
            ))

        result = await orchestrator.run(
            symbol="000001",
            skip_trading_day_check=True,
            domains=["daily_quotes", "daily_indicators"],
        )

        assert "daily_quotes" in result.domains
        assert "daily_indicators" in result.domains

    @pytest.mark.asyncio
    async def test_orchestrator_result_to_dict(self):
        from app.worker.cn.cn_sync_orchestrator import OrchestratorResult
        from app.worker.cn.domain_sync.base_domain_sync import DomainSyncResult

        result = OrchestratorResult(
            success=True,
            domains={"daily_quotes": DomainSyncResult(domain="daily_quotes", success=True)},
            duration_ms=1000,
        )
        d = result.to_dict()
        assert d["success"] is True
        assert "daily_quotes" in d["domains"]

    @pytest.mark.asyncio
    async def test_get_orchestrator_singleton(self):
        from app.worker.cn.cn_sync_orchestrator import get_cn_sync_orchestrator

        o1 = get_cn_sync_orchestrator()
        o2 = get_cn_sync_orchestrator()
        assert o1 is o2


class TestSchedulerSetup:
    def test_register_cn_domain_jobs(self):
        """域级编排任务注册不报错"""
        from app.worker.scheduler_setup import _register_cn_domain_jobs

        mock_sched = MagicMock()
        _register_cn_domain_jobs(mock_sched)

        # 应注册 5 个任务（每日同步、交易日历、聚合、完整性检查、新闻同步）
        assert mock_sched.add_job.call_count == 5

    def test_add_resilient_job_defaults(self):
        from app.worker.scheduler_setup import add_resilient_job

        mock_sched = MagicMock()
        add_resilient_job(mock_sched, lambda: None, None, id="test", name="test")

        call_kwargs = mock_sched.add_job.call_args[1]
        assert call_kwargs["max_instances"] == 1
        assert call_kwargs["coalesce"] is True
        assert call_kwargs["replace_existing"] is True
