"""测试 builtin/loader 工具加载器"""

import pytest
from unittest.mock import patch, MagicMock

from app.engine.tools.builtin.loader import _DOMAIN_MODULES, load_builtin_tools, get_builtin_tool_metas


class TestDomainModules:
    def test_contains_expected_modules(self):
        expected = [
            "market", "news", "fundamentals", "sentiment",
            "china_market", "capital_flow", "macro", "fund", "others",
        ]
        for mod in expected:
            assert mod in _DOMAIN_MODULES

    def test_count_is_nine(self):
        assert len(_DOMAIN_MODULES) == 9


class TestLoadBuiltinTools:
    @patch("app.engine.tools.builtin.loader._import_domain_module")
    def test_returns_list(self, mock_import):
        mock_module = MagicMock()
        mock_module.TOOL_FUNCTIONS = []
        mock_import.return_value = mock_module
        result = load_builtin_tools()
        assert isinstance(result, list)

    @patch("app.engine.tools.builtin.loader._import_domain_module", return_value=None)
    def test_handles_missing_modules(self, mock_import):
        result = load_builtin_tools()
        assert isinstance(result, list)
        assert len(result) == 0


class TestGetBuiltinToolMetas:
    @patch("app.engine.tools.builtin.loader._import_domain_module")
    def test_collects_metas(self, mock_import):
        def dummy_func():
            """测试工具"""
            pass

        mock_module = MagicMock()
        mock_module.TOOL_FUNCTIONS = [dummy_func]
        mock_module.DATA_SOURCE_MAP = {"dummy_func": ["akshare"]}
        mock_module.ANALYST_MAP = {"dummy_func": ["market"]}
        mock_import.return_value = mock_module

        metas = get_builtin_tool_metas()
        assert isinstance(metas, dict)
        assert "dummy_func" in metas
        assert metas["dummy_func"]["data_source_map"] == ["akshare"]
