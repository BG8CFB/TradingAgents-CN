"""CapabilityRegistry 测试 — 新架构 app.data.core.registry.capability"""

from app.data.core.registry.capability import CapabilityRegistry
from app.data.schema.base.enums import SupportLevel


class TestCapabilityRegistry:
    def setup_method(self):
        self.registry = CapabilityRegistry()

    def test_register_and_lookup(self):
        self.registry.register("CN", "daily_quotes", "tushare", SupportLevel.FULL)
        self.registry.register("CN", "daily_quotes", "akshare", SupportLevel.PARTIAL)
        sources = self.registry.get_sources("CN", "daily_quotes")
        assert len(sources) == 2
        assert sources[0] == ("tushare", SupportLevel.FULL)

    def test_unknown_market_returns_empty(self):
        sources = self.registry.get_sources("XX", "daily_quotes")
        assert sources == []

    def test_is_supported(self):
        self.registry.register("CN", "daily_quotes", "tushare", SupportLevel.FULL)
        assert self.registry.is_supported("CN", "daily_quotes", "tushare") is True
        assert self.registry.is_supported("CN", "daily_quotes", "akshare") is False

    def test_ordered_sources_filters_none(self):
        self.registry.register("CN", "daily_indicators", "tushare", SupportLevel.FULL)
        self.registry.register("CN", "daily_indicators", "akshare", SupportLevel.PARTIAL)
        self.registry.register("CN", "daily_indicators", "baostock", SupportLevel.NONE)
        sources = self.registry.get_ordered_sources("CN", "daily_indicators")
        assert "baostock" not in sources
        assert "tushare" in sources
        assert "akshare" in sources

    def test_ordered_sources_with_disabled(self):
        self.registry.register("CN", "daily_quotes", "tushare", SupportLevel.FULL)
        self.registry.register("CN", "daily_quotes", "akshare", SupportLevel.PARTIAL)
        sources = self.registry.get_ordered_sources(
            "CN", "daily_quotes", disabled_sources=["tushare"]
        )
        assert "tushare" not in sources
        assert sources[0] == "akshare"

    def test_ordered_sources_user_priority(self):
        self.registry.register("CN", "daily_quotes", "tushare", SupportLevel.FULL)
        self.registry.register("CN", "daily_quotes", "akshare", SupportLevel.PARTIAL)
        self.registry.register("CN", "daily_quotes", "baostock", SupportLevel.PARTIAL)
        sources = self.registry.get_ordered_sources(
            "CN", "daily_quotes", user_priority=["baostock", "akshare", "tushare"]
        )
        assert sources[0] == "baostock"

    def test_remove_source(self):
        self.registry.register("CN", "daily_quotes", "tushare", SupportLevel.FULL)
        assert self.registry.is_supported("CN", "daily_quotes", "tushare") is True
        self.registry.remove_source("CN", "daily_quotes", "tushare")
        assert self.registry.is_supported("CN", "daily_quotes", "tushare") is False

    def test_load_from_yaml(self):
        yaml_data = {
            "CN": {
                "daily_quotes": {"tushare": "full", "akshare": "partial"},
            }
        }
        self.registry.load_from_yaml(yaml_data)
        assert self.registry.is_supported("CN", "daily_quotes", "tushare") is True
        sources = self.registry.get_sources("CN", "daily_quotes")
        assert len(sources) == 2
