"""DataIntegrityService 测试。

设计原则：不使用 unittest.mock。数据库连接使用 SimulatedMongoDB。
通过 inject_sim_db 注入内存 MongoDB，_get_db 返回 SimulatedMongoDB 实例。
"""

import pytest


class TestIntegrityReport:
    """测试 IntegrityReport 数据类（纯内存逻辑，无外部依赖）。"""

    def test_empty_report(self):
        from app.services.cn_data_integrity_service import IntegrityReport
        report = IntegrityReport()
        assert not report.has_errors
        assert report.error_count == 0
        assert report.warning_count == 0

    def test_report_with_errors(self):
        from app.services.cn_data_integrity_service import IntegrityReport, IntegrityIssue
        report = IntegrityReport()
        report.issues.append(IntegrityIssue(
            severity="error", domain="daily_quotes",
            issue_type="null_fields", description="缺少 symbol",
        ))
        assert report.has_errors
        assert report.error_count == 1

    def test_report_with_warnings(self):
        from app.services.cn_data_integrity_service import IntegrityReport, IntegrityIssue
        report = IntegrityReport()
        report.issues.append(IntegrityIssue(
            severity="warning", domain="daily_quotes",
            issue_type="missing_dates", description="无数据",
        ))
        assert not report.has_errors
        assert report.warning_count == 1

    def test_to_dict(self):
        from app.services.cn_data_integrity_service import IntegrityReport, IntegrityIssue
        report = IntegrityReport(checked_at="2026-05-19T10:00:00")
        report.issues.append(IntegrityIssue(
            severity="error", domain="daily_quotes",
            issue_type="null_fields", description="缺少字段",
            details={"field": "symbol", "null_count": 5},
        ))
        d = report.to_dict()
        assert d["has_errors"] is True
        assert d["error_count"] == 1
        assert len(d["issues"]) == 1
        assert d["issues"][0]["domain"] == "daily_quotes"

    def test_report_with_mixed_issues(self):
        from app.services.cn_data_integrity_service import IntegrityReport, IntegrityIssue
        report = IntegrityReport()
        report.issues.append(IntegrityIssue(
            severity="error", domain="daily_quotes",
            issue_type="null_fields", description="缺少 symbol",
        ))
        report.issues.append(IntegrityIssue(
            severity="warning", domain="basic_info",
            issue_type="missing_dates", description="无数据",
        ))
        assert report.has_errors
        assert report.error_count == 1
        assert report.warning_count == 1
        assert len(report.issues) == 2


class TestIntegrityService:
    """测试 DataIntegrityService（使用 SimulatedMongoDB）。"""

    @pytest.mark.asyncio
    async def test_db_connection_failure_generates_error_report(self):
        """数据库连接失败时生成错误报告。"""
        from app.services.cn_data_integrity_service import DataIntegrityService

        svc = DataIntegrityService()

        async def _raise_error():
            raise Exception("连接失败")

        svc._get_db = _raise_error
        report = await svc.run_full_check()
        assert report.has_errors
        assert any("连接" in i.description for i in report.issues)

    @pytest.mark.asyncio
    async def test_full_check_returns_report(self, inject_sim_db):
        """使用 SimulatedMongoDB 的完整检查返回有效报告。"""
        from app.services.cn_data_integrity_service import DataIntegrityService

        await inject_sim_db["stock_basic_info"].insert_many([
            {"symbol": "000001", "name": "平安银行"},
            {"symbol": "000002", "name": "万科A"},
        ])
        await inject_sim_db["stock_daily_quotes"].insert_one(
            {"symbol": "000001", "trade_date": "2024-06-15", "close": 10.5}
        )

        svc = DataIntegrityService()

        async def _get_sim_db():
            return inject_sim_db

        svc._get_db = _get_sim_db

        report = await svc.run_full_check()

        assert report.checked_at != ""
        assert isinstance(report.to_dict(), dict)

    @pytest.mark.asyncio
    async def test_full_check_saves_report_to_sim_db(self, inject_sim_db):
        """完整检查后将报告保存到 SimulatedMongoDB。"""
        from app.services.cn_data_integrity_service import DataIntegrityService

        svc = DataIntegrityService()

        async def _get_sim_db():
            return inject_sim_db

        svc._get_db = _get_sim_db
        await svc.run_full_check()

        events = await inject_sim_db["sync_events"].find(
            {"event_type": "INTEGRITY_CHECK"}
        ).to_list()
        assert len(events) >= 1
        assert events[0]["domain"] == "all"
        assert "details" in events[0]

    @pytest.mark.asyncio
    async def test_null_field_detection(self, inject_sim_db):
        """检测到空值字段时生成 error 级别问题。"""
        from app.services.cn_data_integrity_service import DataIntegrityService

        await inject_sim_db["stock_daily_quotes"].insert_many([
            {"symbol": "000001", "trade_date": "2024-06-15", "close": 10.5},
            {"symbol": "", "trade_date": "2024-06-15", "close": 11.0},
            {"symbol": "000003", "trade_date": "2024-06-15"},
        ])

        svc = DataIntegrityService()

        async def _get_sim_db():
            return inject_sim_db

        svc._get_db = _get_sim_db
        report = await svc.run_full_check()

        null_issues = [i for i in report.issues if i.issue_type == "null_fields"]
        assert len(null_issues) > 0

    def test_singleton(self):
        from app.services.cn_data_integrity_service import get_integrity_service
        s1 = get_integrity_service()
        s2 = get_integrity_service()
        assert s1 is s2
