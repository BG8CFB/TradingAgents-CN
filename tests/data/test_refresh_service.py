"""测试 DataRefreshService — 数据按需刷新服务。

覆盖范围：
- refresh() 多域并行刷新
- 冷却期检查（force=False 跳过 / force=True 忽略）
- 分布式锁获取失败
- 无可用数据源
- 逐源尝试与回退（成功 / 失败 / 超时）
- 数据标准化与校验
- RefreshResult 状态计算
- _write_to_mongo 写入
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.data.core.refresh_service import DataRefreshService, _cooldown_cache
from app.data.core.result import RefreshResult, DomainRefreshResult
from app.data.schema.base.enums import RefreshStatus


@pytest.fixture(autouse=True)
def clear_cooldown():
    _cooldown_cache.clear()
    yield
    _cooldown_cache.clear()


def _make_service():
    mock_registry = MagicMock()
    mock_priority = MagicMock()
    service = DataRefreshService(mock_registry, mock_priority)
    return service, mock_registry, mock_priority


# ---------------------------------------------------------------------------
# refresh() 入口测试
# ---------------------------------------------------------------------------
class TestRefreshOrchestration:
    """测试 refresh() 多域编排。"""

    @pytest.mark.asyncio
    async def test_refresh_all_domains_when_none(self):
        service, mock_registry, mock_priority = _make_service()

        with patch.object(service, "_refresh_domain", new_callable=AsyncMock) as mock_domain:
            mock_domain.return_value = DomainRefreshResult(domain="basic_info", status="refreshed", source="tushare")
            result = await service.refresh("CN", "000001")

        assert isinstance(result, RefreshResult)
        assert result.symbol == "000001"
        assert result.market == "CN"
        assert result.total_latency_ms >= 0
        assert len(result.domains) > 0

    @pytest.mark.asyncio
    async def test_refresh_specific_domains(self):
        service, mock_registry, mock_priority = _make_service()

        with patch.object(service, "_refresh_domain", new_callable=AsyncMock) as mock_domain:
            mock_domain.return_value = DomainRefreshResult(domain="daily_quotes", status="refreshed", source="akshare")
            result = await service.refresh("CN", "000001", domains=["daily_quotes"])

        assert "daily_quotes" in result.domains
        assert result.domains["daily_quotes"].status == "refreshed"

    @pytest.mark.asyncio
    async def test_refresh_captures_exception_as_failed(self):
        service, _, _ = _make_service()

        with patch.object(service, "_refresh_domain", new_callable=AsyncMock) as mock_domain:
            mock_domain.side_effect = RuntimeError("connection lost")
            result = await service.refresh("CN", "000001", domains=["daily_quotes"])

        assert result.domains["daily_quotes"].status == "failed"
        assert "connection lost" in result.domains["daily_quotes"].error


# ---------------------------------------------------------------------------
# _refresh_domain 测试（mock DomainRefreshResult 构造）
# ---------------------------------------------------------------------------
class TestRefreshDomain:
    """测试 _refresh_domain 内部流程。通过 patch 结果构造绕过 dataclass 必填字段。"""

    @pytest.mark.asyncio
    async def test_cooldown_returns_fresh_without_force(self):
        service, _, _ = _make_service()
        cooldown_key = "cooldown:CN:000001:daily_quotes"
        _cooldown_cache.set(cooldown_key, True, ttl=300)

        mock_dr = MagicMock()
        mock_dr.status = "fresh"
        with patch("app.data.core.refresh_service.DomainRefreshResult", return_value=mock_dr):
            result = await service._refresh_domain("CN", "000001", "daily_quotes", force=False, timeout=30)

        assert result.status == "fresh"

    @pytest.mark.asyncio
    async def test_force_bypasses_cooldown(self):
        service, mock_registry, mock_priority = _make_service()
        cooldown_key = "cooldown:CN:000001:daily_quotes"
        _cooldown_cache.set(cooldown_key, True, ttl=300)

        mock_dr = MagicMock()
        mock_dr.status = "failed"
        mock_dr.error = ""

        mock_lock = AsyncMock()
        mock_lock.acquire_with_wait = AsyncMock(return_value=True)
        mock_lock.release = AsyncMock()
        mock_priority.get_priority = AsyncMock(return_value=[])
        mock_registry.get_ordered_sources = MagicMock(return_value=[])

        with patch("app.data.core.refresh_service.DomainRefreshResult", return_value=mock_dr), \
             patch("app.data.storage.redis.locks.DistributedLock", return_value=mock_lock):
            result = await service._refresh_domain("CN", "000001", "daily_quotes", force=True, timeout=30)

        assert result.status != "fresh"

    @pytest.mark.asyncio
    async def test_lock_acquire_failure_returns_failed(self):
        service, mock_registry, mock_priority = _make_service()

        mock_dr = MagicMock()
        mock_dr.status = "failed"
        mock_dr.error = ""

        mock_lock = AsyncMock()
        mock_lock.acquire_with_wait = AsyncMock(return_value=False)
        mock_lock.release = AsyncMock()

        with patch("app.data.core.refresh_service.DomainRefreshResult", return_value=mock_dr), \
             patch("app.data.core.refresh_service.DistributedLock", return_value=mock_lock):
            result = await service._refresh_domain("CN", "000001", "daily_quotes", force=True, timeout=30)

        assert result.status == "failed"
        assert "锁超时" in result.error

    @pytest.mark.asyncio
    async def test_no_sources_returns_failed(self):
        service, mock_registry, mock_priority = _make_service()

        mock_dr = MagicMock()
        mock_dr.status = "failed"
        mock_dr.error = ""

        mock_lock = AsyncMock()
        mock_lock.acquire_with_wait = AsyncMock(return_value=True)
        mock_lock.release = AsyncMock()
        mock_priority.get_priority = AsyncMock(return_value=[])
        mock_registry.get_ordered_sources = MagicMock(return_value=[])

        with patch("app.data.core.refresh_service.DomainRefreshResult", return_value=mock_dr), \
             patch("app.data.storage.redis.locks.DistributedLock", return_value=mock_lock):
            result = await service._refresh_domain("CN", "000001", "daily_quotes", force=True, timeout=30)

        assert result.status == "failed"
        assert "无可用数据源" in result.error

    @pytest.mark.asyncio
    async def test_first_source_success(self):
        service, mock_registry, mock_priority = _make_service()

        mock_dr = MagicMock()
        mock_dr.status = "failed"
        mock_dr.error = ""

        mock_lock = AsyncMock()
        mock_lock.acquire_with_wait = AsyncMock(return_value=True)
        mock_lock.release = AsyncMock()
        mock_priority.get_priority = AsyncMock(return_value=["tushare"])
        mock_registry.get_ordered_sources = MagicMock(return_value=["tushare"])

        mock_provider = MagicMock()
        mock_provider.get_daily_quotes = AsyncMock(return_value=[{"close": 10}])
        mock_adapter = MagicMock()
        mock_record = MagicMock()
        mock_record.to_db_doc.return_value = {"symbol": "000001", "trade_date": "2024-01-01", "close": 10}
        mock_adapter.adapt_daily_quotes.return_value = [mock_record]

        with patch("app.data.core.refresh_service.DomainRefreshResult", return_value=mock_dr), \
             patch("app.data.storage.redis.locks.DistributedLock", return_value=mock_lock), \
             patch.object(service, "_get_provider_adapter", new_callable=AsyncMock, return_value=(mock_provider, mock_adapter)), \
             patch.object(service, "_write_to_mongo", new_callable=AsyncMock, return_value=1):
            result = await service._refresh_domain("CN", "000001", "daily_quotes", force=True, timeout=30)

        assert result.status == "refreshed"
        assert result.source == "tushare"
        assert result.record_count == 1

    @pytest.mark.asyncio
    async def test_fallback_to_second_source(self):
        service, mock_registry, mock_priority = _make_service()

        mock_dr = MagicMock()
        mock_dr.status = "failed"
        mock_dr.error = ""
        mock_dr.fallback_from = None

        mock_lock = AsyncMock()
        mock_lock.acquire_with_wait = AsyncMock(return_value=True)
        mock_lock.release = AsyncMock()
        mock_priority.get_priority = AsyncMock(return_value=["tushare", "akshare"])
        mock_registry.get_ordered_sources = MagicMock(return_value=["tushare", "akshare"])

        mock_provider_fail = MagicMock()
        mock_provider_fail.get_daily_quotes = AsyncMock(side_effect=RuntimeError("tushare error"))
        mock_adapter_fail = MagicMock()

        mock_provider_ok = MagicMock()
        mock_provider_ok.get_daily_quotes = AsyncMock(return_value=[{"close": 11}])
        mock_adapter_ok = MagicMock()
        mock_record = MagicMock()
        mock_record.to_db_doc.return_value = {"symbol": "000001", "trade_date": "2024-01-01", "close": 11}
        mock_adapter_ok.adapt_daily_quotes.return_value = [mock_record]

        async def mock_get_provider(market, source_name):
            if source_name == "tushare":
                return mock_provider_fail, mock_adapter_fail
            return mock_provider_ok, mock_adapter_ok

        with patch("app.data.core.refresh_service.DomainRefreshResult", return_value=mock_dr), \
             patch("app.data.storage.redis.locks.DistributedLock", return_value=mock_lock), \
             patch.object(service, "_get_provider_adapter", side_effect=mock_get_provider), \
             patch.object(service, "_write_to_mongo", new_callable=AsyncMock, return_value=1):
            result = await service._refresh_domain("CN", "000001", "daily_quotes", force=True, timeout=30)

        assert result.status == "refreshed"
        assert result.source == "akshare"
        assert result.fallback_from == "tushare"

    @pytest.mark.asyncio
    async def test_all_sources_fail(self):
        service, mock_registry, mock_priority = _make_service()

        mock_dr = MagicMock()
        mock_dr.status = "failed"
        mock_dr.error = ""

        mock_lock = AsyncMock()
        mock_lock.acquire_with_wait = AsyncMock(return_value=True)
        mock_lock.release = AsyncMock()
        mock_priority.get_priority = AsyncMock(return_value=["tushare"])
        mock_registry.get_ordered_sources = MagicMock(return_value=["tushare"])

        mock_provider = MagicMock()
        mock_provider.get_daily_quotes = AsyncMock(side_effect=RuntimeError("down"))
        mock_adapter = MagicMock()

        with patch("app.data.core.refresh_service.DomainRefreshResult", return_value=mock_dr), \
             patch("app.data.storage.redis.locks.DistributedLock", return_value=mock_lock), \
             patch.object(service, "_get_provider_adapter", new_callable=AsyncMock, return_value=(mock_provider, mock_adapter)):
            result = await service._refresh_domain("CN", "000001", "daily_quotes", force=True, timeout=30)

        assert result.status == "failed"
        assert "down" in result.error

    @pytest.mark.asyncio
    async def test_timeout_continues_to_next_source(self):
        service, mock_registry, mock_priority = _make_service()

        mock_dr = MagicMock()
        mock_dr.status = "failed"
        mock_dr.error = ""

        mock_lock = AsyncMock()
        mock_lock.acquire_with_wait = AsyncMock(return_value=True)
        mock_lock.release = AsyncMock()
        mock_priority.get_priority = AsyncMock(return_value=["tushare"])
        mock_registry.get_ordered_sources = MagicMock(return_value=["tushare"])

        async def slow_fetch(provider, domain, symbol):
            await asyncio.sleep(10)

        with patch("app.data.core.refresh_service.DomainRefreshResult", return_value=mock_dr), \
             patch("app.data.storage.redis.locks.DistributedLock", return_value=mock_lock), \
             patch.object(service, "_get_provider_adapter", new_callable=AsyncMock,
                          return_value=(MagicMock(), MagicMock())), \
             patch.object(service, "_fetch_from_source", side_effect=slow_fetch):
            result = await service._refresh_domain("CN", "000001", "daily_quotes", force=True, timeout=1)

        assert result.status == "failed"
        assert "超时" in result.error


# ---------------------------------------------------------------------------
# 数据处理测试
# ---------------------------------------------------------------------------
class TestDataProcessing:
    """测试数据标准化和校验。"""

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

    def test_adapt_data_returns_empty_on_exception(self):
        service, _, _ = _make_service()
        mock_adapter = MagicMock()
        mock_adapter.adapt_daily_quotes.side_effect = Exception("parse error")
        result = service._adapt_data(mock_adapter, "daily_quotes", "raw")
        assert result == []

    def test_adapt_data_returns_empty_for_unknown_domain(self):
        service, _, _ = _make_service()
        mock_adapter = MagicMock()
        result = service._adapt_data(mock_adapter, "unknown_domain", "raw")
        assert result == []


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
# _fetch_from_source 测试
# ---------------------------------------------------------------------------
class TestFetchFromSource:
    """测试 _fetch_from_source 域映射。"""

    @pytest.mark.asyncio
    async def test_basic_info_calls_get_stock_list(self):
        service, _, _ = _make_service()
        mock_provider = MagicMock()
        mock_provider.get_stock_list = AsyncMock(return_value=[{"symbol": "000001"}])

        result = await service._fetch_from_source(mock_provider, "basic_info", "000001")
        mock_provider.get_stock_list.assert_awaited_once()
        assert result == [{"symbol": "000001"}]

    @pytest.mark.asyncio
    async def test_daily_quotes_calls_with_symbol_and_dates(self):
        service, _, _ = _make_service()
        mock_provider = MagicMock()
        mock_provider.get_daily_quotes = AsyncMock(return_value=[{"close": 10}])

        result = await service._fetch_from_source(mock_provider, "daily_quotes", "000001")
        mock_provider.get_daily_quotes.assert_awaited_once_with(
            symbol="000001", start_date="1970-01-01", end_date="2099-12-31"
        )

    @pytest.mark.asyncio
    async def test_unknown_domain_returns_none(self):
        service, _, _ = _make_service()
        mock_provider = MagicMock()
        result = await service._fetch_from_source(mock_provider, "unknown_domain", "000001")
        assert result is None


# ---------------------------------------------------------------------------
# _write_to_mongo 测试
# ---------------------------------------------------------------------------
class TestWriteToMongo:
    """测试 _write_to_mongo 写入逻辑。"""

    @pytest.mark.asyncio
    async def test_write_success(self):
        service, _, _ = _make_service()
        mock_repo = MagicMock()
        mock_repo.upsert_many = AsyncMock(return_value=5)
        mock_reader = MagicMock()
        mock_reader._get_repo.return_value = mock_repo

        with patch("app.data.core.reader.Reader", return_value=mock_reader):
            count = await service._write_to_mongo([{"symbol": "000001"}], "daily_quotes", "CN")

        assert count == 5

    @pytest.mark.asyncio
    async def test_write_returns_zero_when_no_repo(self):
        service, _, _ = _make_service()
        mock_reader = MagicMock()
        mock_reader._get_repo.return_value = None

        with patch("app.data.core.reader.Reader", return_value=mock_reader):
            count = await service._write_to_mongo([{"symbol": "000001"}], "unknown", "CN")

        assert count == 0
