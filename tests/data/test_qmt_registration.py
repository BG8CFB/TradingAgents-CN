"""QMT 平台注册测试 — 工厂分支 / 能力矩阵 / 优先级 / 限流 / 常量。

验证 D-2 兜底源语义：qmt 列回退链末位；financial_data/market_quotes
能力为 none（被 get_ordered_sources 过滤）。
"""


from app.data.config import load_yaml
from app.data.core.registry.capability import CapabilityRegistry
from app.data.core.registry.source_metadata import SOURCE_METADATA
from app.constants.data_sources import DATA_SOURCE_REGISTRY, DataSourceCode
from app.data.sources.cn import get_cn_adapter, get_cn_provider
from app.models.config import DataSourceType


class TestFactory:
    def test_provider_and_adapter(self):
        from app.data.sources.cn.qmt.adapter import QmtAdapter
        from app.data.sources.cn.qmt.provider import QmtProvider

        assert isinstance(get_cn_provider("qmt"), QmtProvider)
        assert isinstance(get_cn_adapter("qmt"), QmtAdapter)

    def test_unknown_source_none(self):
        assert get_cn_provider("qmt_hk") is None


class TestCapabilityMatrix:
    """能力矩阵静态注册（不看运行时开关；开关语义见 TestRuntimeSwitch）。"""

    def _sources(self, domain: str, enabled: bool = True) -> list:
        """在 QMT_ENABLED 指定状态下取候选链（开关恢复前完成计算）。"""
        from app.core.config import settings

        original = settings.QMT_ENABLED
        settings.QMT_ENABLED = enabled
        try:
            return CapabilityRegistry().get_ordered_sources("CN", domain)
        finally:
            settings.QMT_ENABLED = original

    def test_qmt_last_in_fallback_chain(self):
        """D-2：qmt 列 daily_quotes 回退链末位。"""
        sources = self._sources("daily_quotes", enabled=True)
        assert "qmt" in sources
        assert sources[-1] == "qmt"

    def test_qmt_excluded_from_none_domains(self):
        """financial_data / market_quotes 能力 none → 不入候选链（O-1/D-7）。"""
        assert "qmt" not in self._sources("financial_data", enabled=True)
        assert "qmt" not in self._sources("market_quotes", enabled=True)

    def test_qmt_supported_domains(self):
        for domain in ("basic_info", "trade_calendar", "adj_factors"):
            assert "qmt" in self._sources(domain, enabled=True)

    def test_support_levels(self):
        registry = CapabilityRegistry()
        assert registry.get_support_level("daily_quotes", "qmt", "CN").value == "partial"
        assert registry.get_support_level("financial_data", "qmt", "CN").value == "none"


class TestDefaultPriorities:
    def test_yaml_contains_qmt_last(self):
        data = load_yaml("default_priorities.yaml")
        cn = data["CN"]
        for domain in ("basic_info", "trade_calendar", "daily_quotes", "adj_factors"):
            assert cn[domain][-1] == "qmt", f"{domain} 的 qmt 应列末位"
        for domain in ("financial_data", "market_quotes"):
            assert "qmt" not in cn[domain]


class TestSourceLimits:
    def test_qmt_metadata(self):
        meta = SOURCE_METADATA["qmt"]
        assert meta.requires_token is False
        assert meta.rate_per_minute == 60
        assert meta.polite_interval_ms == 0
        # datadir 故障自愈慢 → 冷却取长（技术方案 5.2）
        assert meta.circuit_initial_cooldown == 300
        assert meta.circuit_max_cooldown == 1800


class TestConstants:
    def test_data_source_code(self):
        assert DataSourceCode.QMT.value == "qmt"
        info = DATA_SOURCE_REGISTRY[DataSourceCode.QMT]
        assert info.requires_api_key is False
        assert info.is_free is True
        assert "a_shares" in info.supported_markets

    def test_model_enum(self):
        assert DataSourceType.QMT.value == "qmt"


class TestSettings:
    def test_qmt_defaults_safe(self):
        """默认关闭（AGENTS.md 数据源约束）：未配置时行为与现版本一致。"""
        from app.core.config import settings

        assert settings.QMT_ENABLED is False
        assert settings.QMT_READ_WORKERS >= 1
        assert settings.QMT_TICK_RETENTION_DAYS >= 1


class TestRuntimeSwitch:
    """FR-09 GWT：QMT_ENABLED=false 时 qmt 不入候选链（等同未注册）。"""

    def test_disabled_excluded_from_chain(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "QMT_ENABLED", False)
        registry = CapabilityRegistry()
        assert "qmt" not in registry.get_ordered_sources("CN", "daily_quotes")

    def test_enabled_included_last(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "QMT_ENABLED", True)
        registry = CapabilityRegistry()
        sources = registry.get_ordered_sources("CN", "daily_quotes")
        assert sources[-1] == "qmt"


class TestValidatorCompatibility:
    """Validator 必填字段与 partial 源能力对齐（basic_info 仅有 symbol）。"""

    def test_qmt_basic_info_records_pass_validation(self):
        import pandas as pd
        from app.data.processor.validator import Validator
        from app.data.processor.normalizer import Normalizer
        from app.data.sources.cn.qmt.adapter import QmtAdapter

        raw = pd.DataFrame({"ts_code": ["000001.SZ"]})
        records = Normalizer().normalize(raw, "basic_info", QmtAdapter())
        valid, errors = Validator().validate(records, "basic_info", "CN")
        assert len(valid) == 1
        assert errors == []
        assert valid[0]["symbol"] == "000001"

    def test_other_domains_still_require_fields(self):
        from app.data.processor.validator import Validator

        valid, errors = Validator().validate(
            [{"symbol": "000001", "trade_date": "2026-09-09"}], "daily_quotes", "CN"
        )
        assert valid == []
        assert "close" in errors[0]["issues"][0]
