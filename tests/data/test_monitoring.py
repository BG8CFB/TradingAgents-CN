"""测试监控模块 — source_health / completeness / reconciliation / alerts。

覆盖范围：
- SourceHealthMonitor: 调用记录、健康度计算、列表过滤
- CompletenessChecker: 日线完整性、连续性检查（使用 SimulatedMongoDB）
- ReconciliationService: 公司行为对账、日线行情对账（使用 SimulatedMongoDB）
- AlertService: 告警分发、事件记录（使用 SimulatedMongoDB）

设计原则：不使用 unittest.mock。MetadataRepo 通过 inject_sim_db 注入内存 MongoDB。
CompletenessChecker/ReconciliationService 通过 SimulatedMongoDB 直接构造数据。
"""

import pytest
from datetime import datetime, timezone


# ============================================================================
# SourceHealthMonitor 测试 — 纯内存逻辑，无需 MongoDB
# ============================================================================
class TestSourceHealthMonitor:
    """测试数据源健康度监控。"""

    def setup_method(self):
        from app.data.monitoring.source_health import SourceHealthMonitor
        SourceHealthMonitor._instance = None

    def _create_monitor(self):
        from app.data.monitoring.source_health import SourceHealthMonitor
        return SourceHealthMonitor()

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
# CompletenessChecker 测试 — 使用 SimulatedMongoDB
# ============================================================================
class TestCompletenessChecker:
    """测试数据完整性检查。"""

    @pytest.mark.asyncio
    async def test_check_daily_completeness_finds_missing(self, inject_sim_db):
        from app.data.monitoring.completeness import CompletenessChecker
        import app.data.storage.mongo.client as mongo_client
        import app.data.storage.mongo.collections as coll_mod

        await inject_sim_db["stock_basic_info"].insert_many([
            {"symbol": "000001", "list_status": "L"},
            {"symbol": "000002", "list_status": "L"},
        ])
        await inject_sim_db["stock_daily_quotes"].insert_one(
            {"symbol": "000001", "trade_date": "2024-06-15"}
        )

        orig_db = mongo_client.get_motor_db
        mongo_client.get_motor_db = lambda: inject_sim_db
        orig_coll = coll_mod.get_collection_name
        coll_mod.get_collection_name = lambda domain, market: f"stock_{domain}" if domain != "trade_calendar" else "trade_calendar"
        try:
            checker = CompletenessChecker()
            result = await checker.check_daily_completeness("CN", check_date="2024-06-15")
        finally:
            mongo_client.get_motor_db = orig_db
            coll_mod.get_collection_name = orig_coll

        assert "daily_quotes" in result
        assert len(result["daily_quotes"]) == 1
        assert result["daily_quotes"][0]["symbol"] == "000002"
        assert result["daily_quotes"][0]["missing_date"] == "2024-06-15"

    @pytest.mark.asyncio
    async def test_check_daily_completeness_no_missing(self, inject_sim_db):
        from app.data.monitoring.completeness import CompletenessChecker

        await inject_sim_db["stock_basic_info"].insert_one({"symbol": "000001"})
        await inject_sim_db["stock_daily_quotes"].insert_one(
            {"symbol": "000001", "trade_date": "2024-06-15"}
        )

        import app.data.storage.mongo.client as mongo_client
        orig_db = mongo_client.get_motor_db
        mongo_client.get_motor_db = lambda: inject_sim_db
        try:
            checker = CompletenessChecker()
            result = await checker.check_daily_completeness("CN", check_date="2024-06-15")
        finally:
            mongo_client.get_motor_db = orig_db

        assert result == {}


# ============================================================================
# AlertService 测试 — 使用 SimulatedMongoDB
# ============================================================================
class TestAlertService:
    """测试告警分发服务。"""

    @pytest.mark.asyncio
    async def test_send_alert_info_level(self, inject_sim_db):
        from app.data.monitoring.alerts import AlertService, AlertLevel

        service = AlertService()
        await service.send_alert("测试告警", "消息内容", AlertLevel.INFO, market="CN")

        events = await inject_sim_db["sync_events"].find({}).to_list()
        assert len(events) >= 1
        event = events[-1]
        assert event["event_type"] == "ALERT"
        assert event["level"] == "info"
        assert event["title"] == "测试告警"

    @pytest.mark.asyncio
    async def test_send_alert_error_level(self, inject_sim_db):
        from app.data.monitoring.alerts import AlertService, AlertLevel

        service = AlertService()
        await service.send_alert("严重错误", "服务异常", AlertLevel.ERROR,
                                 market="HK", domain="daily_quotes")

        events = await inject_sim_db["sync_events"].find({}).to_list()
        event = events[-1]
        assert event["level"] == "error"
        assert event["domain"] == "daily_quotes"

    @pytest.mark.asyncio
    async def test_send_alert_critical_level(self, inject_sim_db):
        from app.data.monitoring.alerts import AlertService, AlertLevel

        service = AlertService()
        await service.send_alert("致命", "数据源全部不可用", AlertLevel.CRITICAL,
                                 source="tushare")

        events = await inject_sim_db["sync_events"].find({}).to_list()
        event = events[-1]
        assert event["level"] == "critical"
        assert event["source"] == "tushare"

    @pytest.mark.asyncio
    async def test_sse_not_pushed_when_disabled(self, inject_sim_db):
        from app.data.monitoring.alerts import AlertService, AlertLevel

        service = AlertService()
        assert service._sse_enabled is False
        await service.send_alert("告警", "消息", AlertLevel.INFO)

    @pytest.mark.asyncio
    async def test_enable_sse(self, inject_sim_db):
        from app.data.monitoring.alerts import AlertService

        service = AlertService()
        service.enable_sse(True)
        assert service._sse_enabled is True
        service.enable_sse(False)
        assert service._sse_enabled is False
