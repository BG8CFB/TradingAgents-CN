"""CN 域同步模块和调度器测试。"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.data.processor.fallback_router import FetchResult


def _make_fetch_result(**kwargs):
    """辅助：构造 FetchResult（构造函数无参，通过属性赋值）。"""
    r = FetchResult()
    for k, v in kwargs.items():
        setattr(r, k, v)
    return r


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
        mock_router.fetch = AsyncMock(return_value=_make_fetch_result(
            success=True, records=[{"symbol": "000001", "name": "平安银行"}],
            source="tushare",
        ))

        sync = BasicInfoSync(router=mock_router)

        with patch.object(sync, "_write_to_mongo", new_callable=AsyncMock, return_value=1):
            with patch.object(sync, "_write_sync_event", new_callable=AsyncMock):
                with patch.object(sync, "_write_checkpoint", new_callable=AsyncMock):
                    result = await sync.sync()

        assert result.success
        assert result.domain == "basic_info"

    @pytest.mark.asyncio
    async def test_sync_failure(self):
        from app.worker.cn.domain_sync.basic_info_sync import BasicInfoSync

        mock_router = MagicMock()
        mock_router.fetch = AsyncMock(return_value=_make_fetch_result(
            success=False, error="数据源不可用",
            source="tushare",
        ))

        sync = BasicInfoSync(router=mock_router)

        with patch.object(sync, "_write_sync_event", new_callable=AsyncMock):
            with patch.object(sync, "_write_checkpoint", new_callable=AsyncMock):
                result = await sync.sync()

        assert not result.success


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
        mock_router.fetch = AsyncMock(return_value=_make_fetch_result(
            success=True, records=[{"symbol": "000001", "trade_date": "2026-05-19", "close": 10}],
            source="tushare",
        ))

        sync = DailyQuotesSync(router=mock_router)

        with patch.object(sync, "_write_to_mongo", new_callable=AsyncMock, return_value=1):
            with patch.object(sync, "_write_sync_event", new_callable=AsyncMock):
                with patch.object(sync, "_write_checkpoint", new_callable=AsyncMock):
                    result = await sync.sync(symbol="000001")

        assert result.success


class TestSchedulerSetup:
    def test_add_resilient_job_defaults(self):
        from app.worker.scheduler_setup import add_resilient_job

        mock_sched = MagicMock()
        add_resilient_job(mock_sched, lambda: None, None, id="test", name="test")

        call_kwargs = mock_sched.add_job.call_args[1]
        assert call_kwargs["max_instances"] == 1
        assert call_kwargs["coalesce"] is True
        assert call_kwargs["replace_existing"] is True

    def test_get_scheduler_engine_none_by_default(self):
        from app.worker.scheduler_setup import get_scheduler_engine
        engine = get_scheduler_engine()
        assert engine is None
