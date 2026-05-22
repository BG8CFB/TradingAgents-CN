"""core/ 工具模块测试 — DataDomain、SemanticType、MarketType、normalize_symbol、RefreshResult。"""

import pytest

from app.data.core.domain import (
    MARKET_DATA_DOMAINS,
    DataDomain,
    SemanticType,
    DOMAIN_SEMANTIC_TYPE,
)
from app.data.core.market import get_market_timezone, to_market_time, to_utc, is_dst
from app.data.core.result import DomainRefreshResult, RefreshResult
from app.data.schema.base.enums import RefreshStatus
from app.data.schema.base.markets import MarketType, get_full_symbol, normalize_symbol


# ── DataDomain 枚举 ───────────────────────────────────────


class TestDataDomain:
    """DataDomain 枚举值测试。"""

    def test_all_domains_are_strings(self):
        for domain in DataDomain:
            assert isinstance(domain.value, str)

    def test_key_domains_exist(self):
        assert DataDomain.BASIC_INFO.value == "basic_info"
        assert DataDomain.DAILY_QUOTES.value == "daily_quotes"
        assert DataDomain.FINANCIAL_DATA.value == "financial_data"
        assert DataDomain.MARKET_QUOTES.value == "market_quotes"
        assert DataDomain.NEWS.value == "news"
        assert DataDomain.TRADE_CALENDAR.value == "trade_calendar"
        assert DataDomain.ADJ_FACTORS.value == "adj_factors"
        assert DataDomain.CORPORATE_ACTIONS.value == "corporate_actions"
        assert DataDomain.DAILY_INDICATORS.value == "daily_indicators"
        assert DataDomain.CONNECT_STATUS.value == "connect_status"
        assert DataDomain.SOUTHBOUND_HOLDING.value == "southbound_holding"
        assert DataDomain.TUSHARE_UNIVERSE.value == "tushare_universe"
        assert DataDomain.PRE_POST_MARKET.value == "pre_post_market"

    def test_domain_count(self):
        assert len(DataDomain) == 13

    def test_str_enum_behavior(self):
        assert DataDomain.BASIC_INFO == "basic_info"
        assert str(DataDomain.DAILY_QUOTES) == "DataDomain.DAILY_QUOTES"


# ── SemanticType 映射 ─────────────────────────────────────


class TestSemanticType:
    """SemanticType 枚举与映射测试。"""

    def test_all_types_are_strings(self):
        for st in SemanticType:
            assert isinstance(st.value, str)

    def test_entity_type(self):
        assert SemanticType.ENTITY.value == "entity"

    def test_timeseries_type(self):
        assert SemanticType.TIMESERIES.value == "timeseries"

    def test_snapshot_type(self):
        assert SemanticType.SNAPSHOT.value == "snapshot"

    def test_event_type(self):
        assert SemanticType.EVENT.value == "event"

    def test_metadata_type(self):
        assert SemanticType.METADATA.value == "metadata"

    def test_domain_semantic_mapping_complete(self):
        """每个 DataDomain 都有对应的 SemanticType。"""
        for domain in DataDomain:
            assert domain in DOMAIN_SEMANTIC_TYPE

    def test_daily_quotes_is_timeseries(self):
        assert DOMAIN_SEMANTIC_TYPE[DataDomain.DAILY_QUOTES] == SemanticType.TIMESERIES

    def test_basic_info_is_entity(self):
        assert DOMAIN_SEMANTIC_TYPE[DataDomain.BASIC_INFO] == SemanticType.ENTITY

    def test_financial_data_is_snapshot(self):
        assert DOMAIN_SEMANTIC_TYPE[DataDomain.FINANCIAL_DATA] == SemanticType.SNAPSHOT

    def test_news_is_event(self):
        assert DOMAIN_SEMANTIC_TYPE[DataDomain.NEWS] == SemanticType.EVENT

    def test_market_quotes_is_snapshot(self):
        assert DOMAIN_SEMANTIC_TYPE[DataDomain.MARKET_QUOTES] == SemanticType.SNAPSHOT


class TestMarketDataDomains:
    """行情类数据域集合测试。"""

    def test_contains_daily_quotes(self):
        assert DataDomain.DAILY_QUOTES in MARKET_DATA_DOMAINS

    def test_contains_daily_indicators(self):
        assert DataDomain.DAILY_INDICATORS in MARKET_DATA_DOMAINS

    def test_contains_adj_factors(self):
        assert DataDomain.ADJ_FACTORS in MARKET_DATA_DOMAINS

    def test_contains_market_quotes(self):
        assert DataDomain.MARKET_QUOTES in MARKET_DATA_DOMAINS

    def test_not_contains_basic_info(self):
        assert DataDomain.BASIC_INFO not in MARKET_DATA_DOMAINS

    def test_not_contains_news(self):
        assert DataDomain.NEWS not in MARKET_DATA_DOMAINS


# ── MarketType 和 normalize_symbol ────────────────────────


class TestMarketType:
    """MarketType 枚举测试。"""

    def test_cn_value(self):
        assert MarketType.CN.value == "CN"

    def test_hk_value(self):
        assert MarketType.HK.value == "HK"

    def test_us_value(self):
        assert MarketType.US.value == "US"

    def test_from_string(self):
        assert MarketType("CN") == MarketType.CN
        assert MarketType("HK") == MarketType.HK
        assert MarketType("US") == MarketType.US


class TestNormalizeSymbol:
    """normalize_symbol 标准化测试。"""

    def test_cn_strip_suffix_sh(self):
        assert normalize_symbol("600000.SH", "CN") == "600000"

    def test_cn_strip_suffix_sz(self):
        assert normalize_symbol("000001.SZ", "CN") == "000001"

    def test_cn_strip_suffix_bj(self):
        assert normalize_symbol("430001.BJ", "CN") == "430001"

    def test_cn_no_suffix(self):
        assert normalize_symbol("000001", "CN") == "000001"

    def test_hk_strip_dot_hk(self):
        assert normalize_symbol("00700.HK", "HK") == "00700"

    def test_hk_fill_to_5_digits(self):
        assert normalize_symbol("700", "HK") == "00700"

    def test_hk_already_5_digits(self):
        assert normalize_symbol("00001", "HK") == "00001"

    def test_us_uppercase(self):
        assert normalize_symbol("aapl", "US") == "AAPL"

    def test_us_already_upper(self):
        assert normalize_symbol("MSFT", "US") == "MSFT"


class TestGetFullSymbol:
    """get_full_symbol 完整代码测试。"""

    def test_cn_sse_by_prefix(self):
        assert get_full_symbol("600000", "CN") == "600000.SH"

    def test_cn_szse_default(self):
        assert get_full_symbol("000001", "CN") == "000001.SZ"

    def test_cn_bse_by_prefix(self):
        assert get_full_symbol("430001", "CN") == "430001.BJ"

    def test_cn_sse_by_exchange(self):
        assert get_full_symbol("600000", "CN", "SSE") == "600000.SH"

    def test_cn_bse_by_exchange(self):
        assert get_full_symbol("000001", "CN", "BSE") == "000001.BJ"

    def test_cn_68_prefix_is_sh(self):
        assert get_full_symbol("688001", "CN") == "688001.SH"

    def test_hk_adds_dot_hk(self):
        assert get_full_symbol("00700", "HK") == "00700.HK"

    def test_hk_strips_and_fills(self):
        assert get_full_symbol("700.HK", "HK") == "00700.HK"

    def test_us_uppercase(self):
        assert get_full_symbol("aapl", "US") == "AAPL"


# ── 市场时区工具 ──────────────────────────────────────────


class TestMarketTimezone:
    """市场时区工具函数。"""

    def test_cn_timezone(self):
        tz = get_market_timezone("CN")
        assert str(tz) == "Asia/Shanghai"

    def test_hk_timezone(self):
        tz = get_market_timezone("HK")
        assert str(tz) == "Asia/Hong_Kong"

    def test_us_timezone(self):
        tz = get_market_timezone("US")
        assert str(tz) == "America/New_York"

    def test_to_market_time_cn(self):
        from datetime import datetime, timezone
        utc_dt = datetime(2024, 6, 15, 8, 0, tzinfo=timezone.utc)
        cn_dt = to_market_time(utc_dt, "CN")
        assert cn_dt.hour == 16

    def test_to_utc_cn(self):
        from datetime import datetime
        cn_dt = datetime(2024, 6, 15, 16, 0)
        utc_dt = to_utc(cn_dt, "CN")
        assert utc_dt.hour == 8

    def test_is_dst_returns_bool(self):
        result = is_dst("CN")
        assert isinstance(result, bool)


# ── RefreshResult 和 DomainRefreshResult ──────────────────


class TestDomainRefreshResult:
    """单域刷新结果。"""

    def test_defaults(self):
        r = DomainRefreshResult(domain="daily_quotes", status="fresh")
        assert r.domain == "daily_quotes"
        assert r.status == "fresh"
        assert r.record_count == 0
        assert r.source is None
        assert r.fallback_from is None
        assert r.error is None
        assert r.latency_ms == 0

    def test_with_values(self):
        r = DomainRefreshResult(
            domain="daily_quotes",
            status="refreshed",
            record_count=100,
            source="tushare",
            fallback_from="akshare",
            latency_ms=500,
        )
        assert r.record_count == 100
        assert r.source == "tushare"
        assert r.fallback_from == "akshare"

    def test_failed_result(self):
        r = DomainRefreshResult(
            domain="financial_data",
            status="failed",
            error="timeout",
        )
        assert r.status == "failed"
        assert r.error == "timeout"


class TestRefreshResult:
    """多域刷新汇总结果。"""

    def test_default_status_failed(self):
        r = RefreshResult()
        assert r.status == RefreshStatus.FAILED

    def test_compute_status_empty_domains(self):
        r = RefreshResult()
        assert r.compute_status() == RefreshStatus.FAILED

    def test_compute_status_all_fresh(self):
        r = RefreshResult()
        r.domains["daily_quotes"] = DomainRefreshResult(domain="daily_quotes", status="fresh")
        r.domains["basic_info"] = DomainRefreshResult(domain="basic_info", status="fresh")
        assert r.compute_status() == RefreshStatus.FRESH

    def test_compute_status_all_refreshed(self):
        r = RefreshResult()
        r.domains["daily_quotes"] = DomainRefreshResult(domain="daily_quotes", status="refreshed")
        r.domains["basic_info"] = DomainRefreshResult(domain="basic_info", status="refreshed")
        assert r.compute_status() == RefreshStatus.REFRESHED

    def test_compute_status_mixed_fresh_refreshed(self):
        r = RefreshResult()
        r.domains["daily_quotes"] = DomainRefreshResult(domain="daily_quotes", status="fresh")
        r.domains["basic_info"] = DomainRefreshResult(domain="basic_info", status="refreshed")
        assert r.compute_status() == RefreshStatus.REFRESHED

    def test_compute_status_partial_failure(self):
        r = RefreshResult()
        r.domains["daily_quotes"] = DomainRefreshResult(domain="daily_quotes", status="refreshed")
        r.domains["basic_info"] = DomainRefreshResult(domain="basic_info", status="failed")
        status = r.compute_status()
        assert status in (RefreshStatus.PARTIAL, RefreshStatus.FAILED)

    def test_compute_status_all_failed(self):
        r = RefreshResult()
        r.domains["daily_quotes"] = DomainRefreshResult(domain="daily_quotes", status="failed")
        r.domains["basic_info"] = DomainRefreshResult(domain="basic_info", status="failed")
        assert r.compute_status() == RefreshStatus.FAILED

    def test_with_symbol_and_market(self):
        r = RefreshResult(symbol="000001", market="CN")
        assert r.symbol == "000001"
        assert r.market == "CN"

    def test_source_used_tracking(self):
        r = RefreshResult(source_used="tushare", fallback_from="akshare")
        assert r.source_used == "tushare"
        assert r.fallback_from == "akshare"
