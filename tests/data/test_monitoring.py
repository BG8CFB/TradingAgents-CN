"""测试监控模块 — source_health / completeness / reconciliation / alerts。

覆盖范围：
- SourceHealthMonitor: 调用记录、健康度计算、列表过滤、刷入 MongoDB
- CompletenessChecker: 日线完整性、连续性检查、检查报告
- ReconciliationService: 公司行为对账、日线行情对账
- AlertService: 告警分发、SSE 推送、事件记录、级别路由
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone


# ============================================================================
# SourceHealthMonitor 测试
# ============================================================================
class TestSourceHealthMonitor:
    """测试数据源健康度监控。"""

    def setup_method(self):
        from app.data.monitoring.source_health import SourceHealthMonitor
        SourceHealthMonitor._instance = None

    def _create_monitor(self):
        from app.data.monitoring.source_health import SourceHealthMonitor
        with patch("app.data.storage.mongo.repositories.metadata_repo.MetadataRepo"):
            monitor = SourceHealthMonitor()
            return monitor

    def test_record_call_success(self):
        monitor = self._create_monitor()
        monitor.record_call("CN", "tushare", "daily_quotes", success=True, latency_ms=100)

        key = "CN:tushare:daily_quotes"
        assert key in monitor._stats
        assert monitor._stats[key]["success_count"] == 1
        assert monitor._stats[key]["failure_count"] == 0
        assert monitor._stats[key]["total_latency_ms"] == 100
        assert monitor._stats[key]["call_count"] == 1
        assert monitor._stats[key]["last_success_at"] is not None

    def test_record_call_failure(self):
        monitor = self._create_monitor()
        monitor.record_call("CN", "akshare", "daily_quotes", success=False, latency_ms=50, error="timeout")

        key = "CN:akshare:daily_quotes"
        assert key in monitor._stats
        assert monitor._stats[key]["failure_count"] == 1
        assert monitor._stats[key]["last_error"] == "timeout"
        assert monitor._stats[key]["last_failure_at"] is not None

    def test_record_multiple_calls(self):
        monitor = self._create_monitor()
        monitor.record_call("CN", "tushare", "daily_quotes", success=True, latency_ms=100)
        monitor.record_call("CN", "tushare", "daily_quotes", success=False, latency_ms=200, error="err")
        monitor.record_call("CN", "tushare", "daily_quotes", success=True, latency_ms=150)

        key = "CN:tushare:daily_quotes"
        s = monitor._stats[key]
        assert s["success_count"] == 2
        assert s["failure_count"] == 1
        assert s["call_count"] == 3
        assert s["total_latency_ms"] == 450

    def test_get_health_returns_computed_data(self):
        monitor = self._create_monitor()
        monitor.record_call("CN", "tushare", "daily_quotes", success=True, latency_ms=100)
        monitor.record_call("CN", "tushare", "daily_quotes", success=True, latency_ms=200)

        health = monitor.get_health("CN", "tushare", "daily_quotes")
        assert health is not None
        assert health["success_rate"] == 1.0
        assert health["avg_latency_ms"] == 150.0
        assert health["success_count"] == 2
        assert health["failure_count"] == 0

    def test_get_health_returns_none_for_unknown(self):
        monitor = self._create_monitor()
        assert monitor.get_health("US", "unknown", "unknown") is None

    def test_get_health_with_mixed_results(self):
        monitor = self._create_monitor()
        monitor.record_call("CN", "tushare", "daily_quotes", success=True, latency_ms=100)
        monitor.record_call("CN", "tushare", "daily_quotes", success=False, latency_ms=300, error="err")

        health = monitor.get_health("CN", "tushare", "daily_quotes")
        assert health["success_rate"] == 0.5
        assert health["avg_latency_ms"] == 200.0

    def test_get_all_health_filters_by_market(self):
        monitor = self._create_monitor()
        monitor.record_call("CN", "tushare", "daily_quotes", success=True, latency_ms=100)
        monitor.record_call("HK", "yfinance", "daily_quotes", success=True, latency_ms=200)

        cn_health = monitor.get_all_health(market="CN")
        assert len(cn_health) == 1
        assert cn_health[0]["market"] == "CN"

    def test_get_all_health_returns_all_when_no_filter(self):
        monitor = self._create_monitor()
        monitor.record_call("CN", "tushare", "daily_quotes", success=True, latency_ms=100)
        monitor.record_call("HK", "yfinance", "daily_quotes", success=True, latency_ms=200)

        all_health = monitor.get_all_health()
        assert len(all_health) == 2

    def test_compute_health_zero_division_safe(self):
        monitor = self._create_monitor()
        stats = {
            "market": "CN", "source": "tushare", "domain": "daily_quotes",
            "success_count": 0, "failure_count": 0,
            "total_latency_ms": 0, "call_count": 0,
            "last_success_at": None, "last_failure_at": None, "last_error": None,
        }
        health = monitor._compute_health(stats)
        assert health["success_rate"] == 0.0
        assert health["avg_latency_ms"] == 0.0


# ============================================================================
# CompletenessChecker 测试
# ============================================================================
class TestCompletenessChecker:
    """测试数据完整性检查。"""

    @pytest.mark.asyncio
    async def test_check_daily_completeness_finds_missing(self):
        from app.data.monitoring.completeness import CompletenessChecker

        # 构建 mock 数据库，使 db[coll_name] 返回不同集合
        mock_basic_coll = MagicMock()
        mock_basic_cursor = MagicMock()
        mock_basic_cursor.to_list = AsyncMock(return_value=[
            {"symbol": "000001"},
            {"symbol": "000002"},
        ])
        mock_basic_coll.find = MagicMock(return_value=mock_basic_cursor)

        mock_quotes_coll = MagicMock()
        mock_quotes_coll.find_one = AsyncMock(side_effect=[
            {"_id": "exists"},  # 000001 存在
            None,               # 000002 缺失
        ])

        def mock_getitem(name):
            if name == "stock_basic_info":
                return mock_basic_coll
            return mock_quotes_coll

        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(side_effect=mock_getitem)

        with patch("app.data.monitoring.completeness.get_motor_db", return_value=mock_db), \
             patch("app.data.monitoring.completeness.get_collection_name",
                   side_effect=lambda domain, market: f"stock_{domain}"):
            checker = CompletenessChecker()
            result = await checker.check_daily_completeness("CN", check_date="2024-06-15")

        assert "daily_quotes" in result
        assert len(result["daily_quotes"]) == 1
        assert result["daily_quotes"][0]["symbol"] == "000002"
        assert result["daily_quotes"][0]["missing_date"] == "2024-06-15"

    @pytest.mark.asyncio
    async def test_check_daily_completeness_no_missing(self):
        from app.data.monitoring.completeness import CompletenessChecker

        mock_basic_coll = MagicMock()
        mock_basic_cursor = MagicMock()
        mock_basic_cursor.to_list = AsyncMock(return_value=[{"symbol": "000001"}])
        mock_basic_coll.find = MagicMock(return_value=mock_basic_cursor)

        mock_quotes_coll = MagicMock()
        mock_quotes_coll.find_one = AsyncMock(return_value={"_id": "exists"})

        def mock_getitem(name):
            if name == "stock_basic_info":
                return mock_basic_coll
            return mock_quotes_coll

        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(side_effect=mock_getitem)

        with patch("app.data.monitoring.completeness.get_motor_db", return_value=mock_db), \
             patch("app.data.monitoring.completeness.get_collection_name",
                   side_effect=lambda domain, market: f"stock_{domain}"):
            checker = CompletenessChecker()
            result = await checker.check_daily_completeness("CN", check_date="2024-06-15")

        assert result == {}

    @pytest.mark.asyncio
    async def test_check_continuity_finds_gaps(self):
        from app.data.monitoring.completeness import CompletenessChecker

        cal_cursor = MagicMock()
        cal_cursor.to_list = AsyncMock(return_value=[
            {"cal_date": "2024-01-02"},
            {"cal_date": "2024-01-03"},
            {"cal_date": "2024-01-04"},
        ])
        data_cursor = MagicMock()
        data_cursor.to_list = AsyncMock(return_value=[
            {"trade_date": "2024-01-02"},
            {"trade_date": "2024-01-04"},
        ])

        mock_cal_coll = MagicMock()
        mock_cal_coll.find = MagicMock(return_value=cal_cursor)
        mock_data_coll = MagicMock()
        mock_data_coll.find = MagicMock(return_value=data_cursor)

        def mock_getitem(name):
            if name == "trade_calendar":
                return mock_cal_coll
            return mock_data_coll

        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(side_effect=mock_getitem)

        with patch("app.data.monitoring.completeness.get_motor_db", return_value=mock_db), \
             patch("app.data.monitoring.completeness.get_collection_name", return_value="stock_daily_quotes"):
            checker = CompletenessChecker()
            missing = await checker.check_continuity("CN", "000001", start_date="2024-01-02", end_date="2024-01-04")

        assert missing == ["2024-01-03"]

    @pytest.mark.asyncio
    async def test_check_continuity_no_calendar_returns_empty(self):
        from app.data.monitoring.completeness import CompletenessChecker

        cal_cursor = MagicMock()
        cal_cursor.to_list = AsyncMock(return_value=[])

        mock_cal_coll = MagicMock()
        mock_cal_coll.find = MagicMock(return_value=cal_cursor)
        mock_data_coll = MagicMock()

        def mock_getitem(name):
            if name == "trade_calendar":
                return mock_cal_coll
            return mock_data_coll

        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(side_effect=mock_getitem)

        with patch("app.data.monitoring.completeness.get_motor_db", return_value=mock_db), \
             patch("app.data.monitoring.completeness.get_collection_name", return_value="stock_daily_quotes"):
            checker = CompletenessChecker()
            missing = await checker.check_continuity("CN", "000001", start_date="2024-01-01", end_date="2024-01-10")

        assert missing == []

    @pytest.mark.asyncio
    async def test_check_and_report_records_event(self):
        from app.data.monitoring.completeness import CompletenessChecker

        mock_meta = MagicMock()
        mock_meta.insert_event = AsyncMock(return_value=None)

        with patch.object(CompletenessChecker, "check_daily_completeness",
                          new_callable=AsyncMock, return_value={"daily_quotes": [{"symbol": "000001"}]}), \
             patch("app.data.storage.mongo.repositories.metadata_repo.MetadataRepo", return_value=mock_meta):
            checker = CompletenessChecker()
            report = await checker.check_and_report("CN")

        assert report["total_missing"] == 1
        mock_meta.insert_event.assert_awaited_once()
        event = mock_meta.insert_event.call_args[0][0]
        assert event["event_type"] == "COMPLETENESS_CHECK"
        assert event["missing_count"] == 1


# ============================================================================
# ReconciliationService 测试
# ============================================================================
class TestReconciliationService:
    """测试多源对账。"""

    @pytest.mark.asyncio
    async def test_reconcile_corporate_actions_no_data(self):
        from app.data.monitoring.reconciliation import ReconciliationService

        mock_db = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_coll = MagicMock()
        mock_coll.find = MagicMock(return_value=mock_cursor)
        mock_db.__getitem__ = MagicMock(return_value=mock_coll)

        with patch("app.data.monitoring.reconciliation.get_motor_db", return_value=mock_db), \
             patch("app.data.monitoring.reconciliation.get_collection_name", return_value="stock_corporate_actions"):
            service = ReconciliationService()
            result = await service.reconcile_corporate_actions("CN", "000001")

        assert result["total"] == 0
        assert result["matched"] == 0
        assert result["mismatched"] == 0

    @pytest.mark.asyncio
    async def test_reconcile_corporate_actions_consistent(self):
        from app.data.monitoring.reconciliation import ReconciliationService

        docs = [
            {"ex_date": "2024-06-15", "action_type": "cash_dividend", "data_source": "tushare", "amount": 1.5, "ratio_from": 0},
            {"ex_date": "2024-06-15", "action_type": "cash_dividend", "data_source": "akshare", "amount": 1.5, "ratio_from": 0},
        ]
        mock_db = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=docs)
        mock_coll = MagicMock()
        mock_coll.find = MagicMock(return_value=mock_cursor)
        mock_db.__getitem__ = MagicMock(return_value=mock_coll)

        with patch("app.data.monitoring.reconciliation.get_motor_db", return_value=mock_db), \
             patch("app.data.monitoring.reconciliation.get_collection_name", return_value="stock_corporate_actions"):
            service = ReconciliationService()
            result = await service.reconcile_corporate_actions("CN", "000001")

        assert result["total"] == 1
        assert result["matched"] == 1
        assert result["mismatched"] == 0

    @pytest.mark.asyncio
    async def test_reconcile_corporate_actions_inconsistent(self):
        from app.data.monitoring.reconciliation import ReconciliationService

        docs = [
            {"ex_date": "2024-06-15", "action_type": "cash_dividend", "data_source": "tushare", "amount": 1.5, "ratio_from": 0},
            {"ex_date": "2024-06-15", "action_type": "cash_dividend", "data_source": "akshare", "amount": 2.0, "ratio_from": 0},
        ]
        mock_db = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=docs)
        mock_coll = MagicMock()
        mock_coll.find = MagicMock(return_value=mock_cursor)
        mock_db.__getitem__ = MagicMock(return_value=mock_coll)

        with patch("app.data.monitoring.reconciliation.get_motor_db", return_value=mock_db), \
             patch("app.data.monitoring.reconciliation.get_collection_name", return_value="stock_corporate_actions"):
            service = ReconciliationService()
            result = await service.reconcile_corporate_actions("CN", "000001")

        assert result["mismatched"] == 1
        assert len(result["details"]) == 1

    @pytest.mark.asyncio
    async def test_reconcile_corporate_actions_single_source(self):
        from app.data.monitoring.reconciliation import ReconciliationService

        docs = [
            {"ex_date": "2024-06-15", "action_type": "cash_dividend", "data_source": "tushare", "amount": 1.5, "ratio_from": 0},
        ]
        mock_db = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=docs)
        mock_coll = MagicMock()
        mock_coll.find = MagicMock(return_value=mock_cursor)
        mock_db.__getitem__ = MagicMock(return_value=mock_coll)

        with patch("app.data.monitoring.reconciliation.get_motor_db", return_value=mock_db), \
             patch("app.data.monitoring.reconciliation.get_collection_name", return_value="stock_corporate_actions"):
            service = ReconciliationService()
            result = await service.reconcile_corporate_actions("CN", "000001")

        assert result["total"] == 1
        assert result["matched"] == 1

    @pytest.mark.asyncio
    async def test_reconcile_quotes_found(self):
        from app.data.monitoring.reconciliation import ReconciliationService

        mock_coll = MagicMock()
        mock_coll.find_one = AsyncMock(return_value={
            "symbol": "000001", "trade_date": "2024-06-15", "close": 10.5, "volume": 1000,
        })
        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_coll)

        with patch("app.data.monitoring.reconciliation.get_motor_db", return_value=mock_db), \
             patch("app.data.monitoring.reconciliation.get_collection_name", return_value="stock_daily_quotes"):
            service = ReconciliationService()
            result = await service.reconcile_quotes("CN", "000001", "2024-06-15")

        assert result["status"] == "ok"
        assert result["close"] == 10.5
        assert result["volume"] == 1000

    @pytest.mark.asyncio
    async def test_reconcile_quotes_missing(self):
        from app.data.monitoring.reconciliation import ReconciliationService

        mock_coll = MagicMock()
        mock_coll.find_one = AsyncMock(return_value=None)
        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_coll)

        with patch("app.data.monitoring.reconciliation.get_motor_db", return_value=mock_db), \
             patch("app.data.monitoring.reconciliation.get_collection_name", return_value="stock_daily_quotes"):
            service = ReconciliationService()
            result = await service.reconcile_quotes("CN", "000001", "2024-06-15")

        assert result["status"] == "missing"


# ============================================================================
# AlertService 测试
# ============================================================================
class TestAlertService:
    """测试告警分发服务。MetadataRepo 是延迟导入的。"""

    @pytest.mark.asyncio
    async def test_send_alert_info_level(self):
        from app.data.monitoring.alerts import AlertService, AlertLevel

        mock_meta = MagicMock()
        mock_meta.insert_event = AsyncMock(return_value=None)

        with patch("app.data.storage.mongo.repositories.metadata_repo.MetadataRepo", return_value=mock_meta):
            service = AlertService()
            await service.send_alert("测试告警", "消息内容", AlertLevel.INFO, market="CN")

        mock_meta.insert_event.assert_awaited_once()
        event = mock_meta.insert_event.call_args[0][0]
        assert event["event_type"] == "ALERT"
        assert event["level"] == "info"
        assert event["title"] == "测试告警"

    @pytest.mark.asyncio
    async def test_send_alert_error_level(self):
        from app.data.monitoring.alerts import AlertService, AlertLevel

        mock_meta = MagicMock()
        mock_meta.insert_event = AsyncMock(return_value=None)

        with patch("app.data.storage.mongo.repositories.metadata_repo.MetadataRepo", return_value=mock_meta):
            service = AlertService()
            await service.send_alert("严重错误", "服务异常", AlertLevel.ERROR, market="HK", domain="daily_quotes")

        event = mock_meta.insert_event.call_args[0][0]
        assert event["level"] == "error"
        assert event["domain"] == "daily_quotes"

    @pytest.mark.asyncio
    async def test_send_alert_critical_level(self):
        from app.data.monitoring.alerts import AlertService, AlertLevel

        mock_meta = MagicMock()
        mock_meta.insert_event = AsyncMock(return_value=None)

        with patch("app.data.storage.mongo.repositories.metadata_repo.MetadataRepo", return_value=mock_meta):
            service = AlertService()
            await service.send_alert("致命", "数据源全部不可用", AlertLevel.CRITICAL, source="tushare")

        event = mock_meta.insert_event.call_args[0][0]
        assert event["level"] == "critical"
        assert event["source"] == "tushare"

    @pytest.mark.asyncio
    async def test_sse_not_pushed_when_disabled(self):
        from app.data.monitoring.alerts import AlertService, AlertLevel

        mock_meta = MagicMock()
        mock_meta.insert_event = AsyncMock(return_value=None)

        with patch("app.data.storage.mongo.repositories.metadata_repo.MetadataRepo", return_value=mock_meta):
            service = AlertService()
            assert service._sse_enabled is False
            await service.send_alert("告警", "消息", AlertLevel.INFO)

    @pytest.mark.asyncio
    async def test_enable_sse(self):
        from app.data.monitoring.alerts import AlertService

        service = AlertService()
        service.enable_sse(True)
        assert service._sse_enabled is True
        service.enable_sse(False)
        assert service._sse_enabled is False

    @pytest.mark.asyncio
    async def test_record_event_failure_does_not_raise(self):
        from app.data.monitoring.alerts import AlertService, AlertLevel

        with patch("app.data.storage.mongo.repositories.metadata_repo.MetadataRepo", side_effect=Exception("MongoDB down")):
            service = AlertService()
            await service.send_alert("告警", "消息", AlertLevel.WARNING, market="CN")
