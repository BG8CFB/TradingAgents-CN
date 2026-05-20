"""CapabilityRegistry 测试"""

from app.data.processor.capability_registry import CapabilityRegistry, SupportLevel, CN_CAPABILITY_MATRIX, ALL_DOMAINS


class TestCapabilityRegistry:
    def setup_method(self):
        self.registry = CapabilityRegistry()

    def test_all_domains_defined(self):
        assert len(ALL_DOMAINS) == 8

    def test_support_level_lookup(self):
        assert self.registry.get_support_level("daily_quotes", "tushare") == SupportLevel.FULL
        assert self.registry.get_support_level("daily_indicators", "baostock") == SupportLevel.NONE
        assert self.registry.get_support_level("daily_indicators", "akshare") == SupportLevel.PARTIAL

    def test_unknown_domain_returns_none(self):
        assert self.registry.get_support_level("nonexistent", "tushare") == SupportLevel.NONE

    def test_unknown_source_returns_none(self):
        assert self.registry.get_support_level("daily_quotes", "nonexistent") == SupportLevel.NONE

    def test_available_sources_excludes_none(self):
        sources = self.registry.get_available_sources("daily_indicators")
        assert "tushare" in sources
        assert "akshare" in sources
        assert "baostock" not in sources

    def test_ordered_sources_default_priority(self):
        ordered = self.registry.get_ordered_sources("daily_quotes")
        assert ordered[0] == "tushare"
        assert ordered[-1] == "baostock"

    def test_ordered_sources_with_disabled(self):
        ordered = self.registry.get_ordered_sources("daily_quotes", disabled_sources=["tushare"])
        assert "tushare" not in ordered
        assert ordered[0] == "akshare"

    def test_ordered_sources_user_priority(self):
        ordered = self.registry.get_ordered_sources("daily_quotes", user_priority=["baostock", "akshare", "tushare"])
        assert ordered[0] == "baostock"

    def test_set_user_priority(self):
        self.registry.set_user_priority("daily_quotes", ["akshare", "tushare"])
        ordered = self.registry.get_ordered_sources("daily_quotes")
        assert ordered[0] == "akshare"

    def test_get_default_priority(self):
        priority = CapabilityRegistry.get_default_priority("daily_indicators")
        assert priority == ["tushare", "akshare"]

    def test_get_matrix_summary(self):
        summary = self.registry.get_matrix_summary()
        assert "daily_quotes" in summary
        assert summary["daily_quotes"]["tushare"] == "full"

    def test_financial_only_tushare_akshare(self):
        sources = self.registry.get_available_sources("financial")
        assert "tushare" in sources
        assert "akshare" in sources
        assert "baostock" not in sources
