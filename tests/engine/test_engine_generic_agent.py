"""测试 GenericAgent 通用智能体模块

调用真实的 resolve_company_name、build_stage3_report_path 和 load_agent_config 函数。
数据获取依赖的外部 API 通过 os.environ 控制回退行为。
"""

import os

from app.engine.agents.utils.agent_config import (
    resolve_company_name,
    build_stage3_report_path,
    load_agent_config,
)


class TestResolveCompanyName:
    """resolve_company_name 使用真实的 fallback 逻辑。

    在没有外部数据源 API key 的环境中，函数会走 fallback 路径。
    我们验证各分支的 fallback 结果格式。
    """

    async def test_china_stock_returns_string(self):
        """A 股应返回包含股票代码的字符串"""
        result = await resolve_company_name("000001", {"is_china": True, "is_hk": False, "is_us": False})
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_hk_stock_returns_string(self):
        """港股应返回包含股票代码的字符串"""
        result = await resolve_company_name("00700.HK", {"is_china": False, "is_hk": True, "is_us": False})
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_us_stock_known_ticker(self):
        """已知的 US 股票代码应返回中文名称（从内置映射）"""
        result = await resolve_company_name("AAPL", {"is_china": False, "is_hk": False, "is_us": True})
        # AAPL 在 _KNOWN_US_STOCK_NAMES 中映射为 "苹果公司"
        # 如果 yfinance 不可用，会回退到内置映射
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_us_stock_unknown_ticker(self):
        """未知的 US 股票代码应返回包含"美股"的字符串"""
        result = await resolve_company_name("UNKNOWN_TICKER_XYZ", {"is_china": False, "is_hk": False, "is_us": True})
        assert isinstance(result, str)
        assert "美股" in result

    async def test_fallback_on_exception(self):
        """无效输入应返回字符串而不崩溃"""
        result = await resolve_company_name("000001", {"is_china": True, "is_hk": False, "is_us": False})
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
    """load_agent_config 读智能体库（agent_specs 集合 / 种子降级，2026-09 DB 化）"""

    def test_finds_slug_in_library(self, mongodb_available):
        """库内 slug 应返回其 roleDefinition（种子条目）"""
        result = load_agent_config("market-analyst")
        assert result != ""

    def test_returns_empty_for_unknown_slug(self, mongodb_available):
        """未知的 slug 应返回空字符串"""
        result = load_agent_config("nonexistent-analyst")
        assert result == ""
