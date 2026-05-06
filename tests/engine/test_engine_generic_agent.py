"""测试 GenericAgent 通用智能体模块"""

import os
import pytest
from unittest.mock import patch, MagicMock

from app.engine.agents.utils.generic_agent import (
    resolve_company_name,
    build_stage3_report_path,
    load_agent_config,
)


class TestResolveCompanyName:
    def test_china_stock_path(self):
        with patch("app.data.data_source_manager.get_china_stock_info_unified", return_value={"name": "平安银行"}):
            result = resolve_company_name("000001", {"is_china": True, "is_hk": False, "is_us": False})
            assert result == "平安银行"

    def test_china_stock_fallback_to_interface(self):
        with patch("app.data.data_source_manager.get_china_stock_info_unified", side_effect=Exception("err")):
            with patch("app.data.interface.get_china_stock_info_unified", return_value="股票代码:000001\n股票名称:平安银行"):
                result = resolve_company_name("000001", {"is_china": True, "is_hk": False, "is_us": False})
                assert result == "平安银行"

    def test_china_stock_no_name(self):
        with patch("app.data.data_source_manager.get_china_stock_info_unified", side_effect=Exception("err")):
            with patch("app.data.interface.get_china_stock_info_unified", return_value="无名称信息"):
                result = resolve_company_name("000001", {"is_china": True, "is_hk": False, "is_us": False})
                assert "000001" in result

    def test_hk_stock_path(self):
        with patch("app.data.providers.hk.improved_hk.get_hk_company_name_improved", return_value="腾讯控股"):
            result = resolve_company_name("00700.HK", {"is_china": False, "is_hk": True, "is_us": False})
            assert result == "腾讯控股"

    def test_hk_stock_fallback(self):
        with patch("app.data.providers.hk.improved_hk.get_hk_company_name_improved", side_effect=Exception("err")):
            result = resolve_company_name("00700.HK", {"is_china": False, "is_hk": True, "is_us": False})
            assert "港股" in result

    def test_us_stock_known_name(self):
        with patch("app.data.providers.us.yfinance.YFinanceUtils.get_stock_info", return_value={}):
            result = resolve_company_name("AAPL", {"is_china": False, "is_hk": False, "is_us": True})
            assert "苹果" in result

    def test_us_stock_yfinance(self):
        with patch("app.data.providers.us.yfinance.YFinanceUtils.get_stock_info", return_value={"shortName": "Apple Inc"}):
            result = resolve_company_name("AAPL", {"is_china": False, "is_hk": False, "is_us": True})
            assert result == "Apple Inc"

    def test_us_stock_unknown_ticker(self):
        with patch("app.data.providers.us.yfinance.YFinanceUtils.get_stock_info", return_value={}):
            result = resolve_company_name("UNKNOWN", {"is_china": False, "is_hk": False, "is_us": True})
            assert "美股" in result

    def test_fallback_on_exception(self):
        result = resolve_company_name("000001", {"is_china": True, "is_hk": False, "is_us": False, "invalid": True})
        assert isinstance(result, str)


class TestBuildStage3ReportPath:
    def test_produces_valid_path(self):
        path = build_stage3_report_path("task-123", "000001", "risk_report")
        assert "task-123" in path
        assert "000001" in path
        assert "risk_report" in path
        assert path.endswith(".md")

    def test_sanitizes_special_chars(self):
        path = build_stage3_report_path("task/with/slashes", "000001", "report")
        assert "/" not in os.path.basename(path).replace(".md", "").split("_")[0]

    def test_none_task_id_uses_ticker(self):
        path = build_stage3_report_path(None, "600519", "report")
        assert path.endswith(".md")

    def test_empty_strings_handled(self):
        path = build_stage3_report_path("", "", "report")
        assert path.endswith(".md")


class TestLoadAgentConfig:
    def test_finds_slug_in_config(self):
        config_content = """
customModes:
  - slug: market-analyst
    roleDefinition: "你是市场分析师"
"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            import yaml
            config_path = os.path.join(tmpdir, "phase1_agents_config.yaml")
            with open(config_path, "w", encoding="utf-8") as f:
                f.write(config_content)

            with patch.dict(os.environ, {"AGENT_CONFIG_DIR": tmpdir}):
                result = load_agent_config("market-analyst")
                assert "市场分析师" in result

    def test_returns_empty_for_unknown_slug(self):
        with patch.dict(os.environ, {"AGENT_CONFIG_DIR": "/nonexistent"}):
            result = load_agent_config("nonexistent-analyst")
            assert result == ""
