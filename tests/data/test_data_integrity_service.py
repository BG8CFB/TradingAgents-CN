"""DataIntegrityService 测试"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestIntegrityReport:
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


class TestIntegrityService:
    @pytest.mark.asyncio
    async def test_db_connection_failure(self):
        """数据库连接失败时生成错误报告"""
        from app.services.cn_data_integrity_service import DataIntegrityService

        svc = DataIntegrityService()
        svc._get_db = AsyncMock(side_effect=Exception("连接失败"))

        report = await svc.run_full_check()
        assert report.has_errors
        assert any("连接" in i.description for i in report.issues)

    @pytest.mark.asyncio
    async def test_full_check_returns_report(self):
        """完整检查返回有效报告"""
        from app.services.cn_data_integrity_service import DataIntegrityService

        mock_db = MagicMock()
        mock_collection = MagicMock()

        # Mock count_documents
        mock_collection.count_documents = AsyncMock(return_value=100)
        mock_collection.find = MagicMock()
        mock_collection.aggregate = AsyncMock(return_value=[])
        mock_collection.insert_one = AsyncMock()

        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        svc = DataIntegrityService()
        svc._get_db = AsyncMock(return_value=mock_db)
        svc._save_report = AsyncMock()

        report = await svc.run_full_check()

        assert report.checked_at != ""
        assert isinstance(report.to_dict(), dict)

    def test_singleton(self):
        from app.services.cn_data_integrity_service import get_integrity_service
        s1 = get_integrity_service()
        s2 = get_integrity_service()
        assert s1 is s2
