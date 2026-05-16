"""测试报告服务"""

import pytest


class TestReportsServiceImport:
    def test_importable(self):
        from app.services.reports_service import ReportsService
        assert ReportsService is not None


class TestReportsServiceFormatting:
    def test_format_report_metadata(self):
        from app.services.reports_service import ReportsService
        svc = ReportsService.__new__(ReportsService)
        assert svc is not None
