"""期限贯通 core 层测试：映射表、取数函数、等待上限、默认池约束。"""
from app.core.horizons import (
    HORIZON_DAYS,
    HORIZON_DEFAULT_POOL,
    AnalysisHorizon,
    horizon_days_of,
    horizon_label,
    max_wait_days,
)


class TestHorizonMapping:
    def test_three_tiers_with_monotonic_days(self):
        assert list(HORIZON_DAYS) == ["short", "mid", "long"]
        days = list(HORIZON_DAYS.values())
        assert days == sorted(days)
        assert HORIZON_DAYS == {"short": 7, "mid": 20, "long": 60}

    def test_horizon_days_of_each_tier(self):
        assert horizon_days_of("short") == 7
        assert horizon_days_of("mid") == 20
        assert horizon_days_of("long") == 60

    def test_horizon_days_of_none_and_unknown(self):
        assert horizon_days_of(None) is None
        assert horizon_days_of("medium") is None
        assert horizon_days_of("") is None

    def test_horizon_days_of_case_insensitive(self):
        assert horizon_days_of("SHORT") == 7
        assert horizon_days_of(" Mid ") == 20

    def test_horizon_label(self):
        assert horizon_label("short") == "短线"
        assert horizon_label("mid") == "中线"
        assert horizon_label("long") == "长线"
        assert horizon_label(None) == ""
        assert horizon_label("bogus") == ""


class TestMaxWaitDays:
    def test_short_and_mid_keep_legacy_90(self):
        # 现行为零漂移：原 _MAX_WAIT_DAYS=90 对 7/20 日档保持不变
        assert max_wait_days(7) == 90
        assert max_wait_days(20) == 90

    def test_long_gets_headroom_for_double_holidays(self):
        # 60 交易日 ≈ 84 自然日，春节+国庆连跨可达 105+；130 有充足余量
        assert max_wait_days(60) == 130

    def test_nonpositive_falls_back_to_90(self):
        assert max_wait_days(0) == 90
        assert max_wait_days(-5) == 90


class TestDefaultPool:
    def test_every_tier_keeps_required_sources(self):
        # market/short-term-capital 是 trader/bull/bear 的 required_sources，裁了编译期拒绝
        for pool in HORIZON_DEFAULT_POOL.values():
            assert "market-analyst" in pool
            assert "short-term-capital-analyst" in pool

    def test_short_pool_matches_current_default(self):
        assert set(HORIZON_DEFAULT_POOL["short"]) == {
            "market-analyst",
            "financial-news-analyst",
            "china-market-analyst",
            "social-media-analyst",
            "short-term-capital-analyst",
        }

    def test_mid_long_add_fundamentals_drop_social(self):
        for tier in ("mid", "long"):
            assert "fundamentals-analyst" in HORIZON_DEFAULT_POOL[tier]
            assert "social-media-analyst" not in HORIZON_DEFAULT_POOL[tier]


class TestEnumContract:
    def test_enum_values_are_api_stable(self):
        assert AnalysisHorizon.SHORT.value == "short"
        assert AnalysisHorizon.MID.value == "mid"
        assert AnalysisHorizon.LONG.value == "long"
