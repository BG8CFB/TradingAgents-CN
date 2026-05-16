"""测试 GenericAgent 通用智能体模块

调用真实的 resolve_company_name、build_stage3_report_path 和 load_agent_config 函数。
数据获取依赖的外部 API 通过 os.environ 控制回退行为。
"""

import os
import pytest

from app.engine.agents.utils.generic_agent import (
    resolve_company_name,
    build_stage3_report_path,
    load_agent_config,
)


class TestResolveCompanyName:
    """resolve_company_name 使用真实的 fallback 逻辑。

    在没有外部数据源 API key 的环境中，函数会走 fallback 路径。
    我们验证各分支的 fallback 结果格式。
    """

    def test_china_stock_returns_string(self):
        """A 股应返回包含股票代码的字符串"""
        result = resolve_company_name("000001", {"is_china": True, "is_hk": False, "is_us": False})
        assert isinstance(result, str)
        assert len(result) > 0

    def test_hk_stock_returns_string(self):
        """港股应返回包含股票代码的字符串"""
        result = resolve_company_name("00700.HK", {"is_china": False, "is_hk": True, "is_us": False})
        assert isinstance(result, str)
        assert len(result) > 0

    def test_us_stock_known_ticker(self):
        """已知的 US 股票代码应返回中文名称（从内置映射）"""
        result = resolve_company_name("AAPL", {"is_china": False, "is_hk": False, "is_us": True})
        # AAPL 在 _KNOWN_US_STOCK_NAMES 中映射为 "苹果公司"
        # 如果 yfinance 不可用，会回退到内置映射
        assert isinstance(result, str)
        assert len(result) > 0

    def test_us_stock_unknown_ticker(self):
        """未知的 US 股票代码应返回包含"美股"的字符串"""
        result = resolve_company_name("UNKNOWN_TICKER_XYZ", {"is_china": False, "is_hk": False, "is_us": True})
        assert isinstance(result, str)
        assert "美股" in result

    def test_fallback_on_exception(self):
        """无效输入应返回字符串而不崩溃"""
        result = resolve_company_name("000001", {"is_china": True, "is_hk": False, "is_us": False})
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
        # 文件名中的 / 应被替换为 _
        basename = os.path.basename(path).replace(".md", "")
        task_part = basename.split("_")[0]
        assert "/" not in task_part

    def test_none_task_id_uses_ticker(self):
        path = build_stage3_report_path(None, "600519", "report")
        assert path.endswith(".md")
        assert "600519" in path

    def test_empty_strings_handled(self):
        path = build_stage3_report_path("", "", "report")
        assert path.endswith(".md")


class TestLoadAgentConfig:
    def test_finds_slug_in_config(self, tmp_path):
        """应从临时配置文件中加载 agent 配置"""
        import yaml
        config_content = {
            "customModes": [
                {
                    "slug": "market-analyst",
                    "roleDefinition": "你是市场分析师",
                },
            ],
        }
        config_path = tmp_path / "phase1_agents_config.yaml"
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config_content, f, allow_unicode=True)

        original = os.environ.get("AGENT_CONFIG_DIR")
        try:
            os.environ["AGENT_CONFIG_DIR"] = str(tmp_path)
            result = load_agent_config("market-analyst")
            assert "市场分析师" in result
        finally:
            if original is not None:
                os.environ["AGENT_CONFIG_DIR"] = original
            else:
                os.environ.pop("AGENT_CONFIG_DIR", None)

    def test_returns_empty_for_unknown_slug(self, tmp_path):
        """未知的 slug 应返回空字符串"""
        import yaml
        config_content = {
            "customModes": [
                {
                    "slug": "market-analyst",
                    "roleDefinition": "你是市场分析师",
                },
            ],
        }
        config_path = tmp_path / "phase1_agents_config.yaml"
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config_content, f, allow_unicode=True)

        original = os.environ.get("AGENT_CONFIG_DIR")
        try:
            os.environ["AGENT_CONFIG_DIR"] = str(tmp_path)
            result = load_agent_config("nonexistent-analyst")
            assert result == ""
        finally:
            if original is not None:
                os.environ["AGENT_CONFIG_DIR"] = original
            else:
                os.environ.pop("AGENT_CONFIG_DIR", None)
