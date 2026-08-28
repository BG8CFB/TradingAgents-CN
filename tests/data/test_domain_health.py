"""域健康判定模型单测 — 判定矩阵全覆盖（纯逻辑，无 I/O）。"""

from datetime import datetime, timedelta, timezone

import pytest

from app.data.core.health import DomainHealthCalculator


@pytest.fixture
def calc():
    return DomainHealthCalculator()


def _src(source="tushare", circuit="closed", calls=100, rate=1.0, latency=100.0):
    return {
        "source": source,
        "circuit_state": circuit,
        "total_calls": calls,
        "total_calls_1h": calls,
        "success_rate_1h": rate,
        "avg_latency_1h": latency,
        "consecutive_failures": 0,
    }


NOW = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
RECENT = (NOW - timedelta(hours=1)).isoformat()
OLD = (NOW - timedelta(days=10)).isoformat()


def test_monitoring_unavailable_is_unknown(calc):
    r = calc.evaluate("CN", "daily_quotes", 100, RECENT, True,
                      [_src()], monitoring_available=False)
    assert r["status"] == "unknown"


def test_no_data_when_empty_and_never_synced(calc):
    r = calc.evaluate("CN", "daily_quotes", 0, None, False, [_src()])
    assert r["status"] == "no_data"


def test_stale_when_data_older_than_budget(calc):
    # daily_quotes CN 预算 72h（trading_day_after_close → data_health 覆盖）
    r = calc.evaluate("CN", "daily_quotes", 100, OLD, True, [_src()], now=NOW)
    assert r["status"] == "stale"
    assert r["freshness"]["actual_hours"] > r["freshness"]["budget_hours"]


def test_unhealthy_when_all_sources_open(calc):
    r = calc.evaluate("CN", "daily_quotes", 100, RECENT, True,
                      [_src(circuit="open")])
    assert r["status"] == "unhealthy"


def test_degraded_when_open_but_fallback_available(calc):
    r = calc.evaluate("CN", "daily_quotes", 100, RECENT, True,
                      [_src("tushare", circuit="open"), _src("akshare")], now=NOW)
    assert r["status"] == "degraded"


def test_low_success_rate_unhealthy_with_samples(calc):
    r = calc.evaluate("CN", "daily_quotes", 100, RECENT, True,
                      [_src(calls=100, rate=0.3)])
    assert r["status"] == "unhealthy"


def test_low_success_rate_ignored_without_samples(calc):
    # 样本不足（1 次调用成功）不得参与判定 —— 防 noise
    r = calc.evaluate("CN", "daily_quotes", 100, RECENT, True,
                      [_src(calls=1, rate=1.0)], now=NOW)
    assert r["status"] == "healthy"


def test_latency_over_budget_degraded(calc):
    r = calc.evaluate("CN", "daily_quotes", 100, RECENT, True,
                      [_src(calls=100, rate=1.0, latency=9000.0)], now=NOW)
    assert r["status"] == "degraded"


def test_low_coverage_degraded(calc):
    r = calc.evaluate("CN", "daily_quotes", 100, RECENT, True, [_src()], coverage=0.3, now=NOW)
    assert r["status"] == "degraded"


def test_coverage_exempt_domain_skips_coverage(calc):
    # news 在豁免列表，覆盖率不参与判定
    r = calc.evaluate("CN", "news", 10, RECENT, True, [_src()], coverage=0.001, now=NOW)
    assert r["status"] == "healthy"
    assert r["coverage"] is None


def test_no_source_signal_fresh_data_is_healthy_not_unknown(calc):
    r = calc.evaluate("CN", "daily_quotes", 100, RECENT, True, sources=[], now=NOW)
    assert r["status"] == "healthy"
    assert "无运行时源调用信号" in r["reason"]


def test_no_source_signal_stale_data_is_stale(calc):
    r = calc.evaluate("CN", "daily_quotes", 100, OLD, True, sources=[], now=NOW)
    assert r["status"] == "stale"


def test_zero_call_source_serialized_as_unknown(calc):
    r = calc.evaluate("CN", "daily_quotes", 100, RECENT, True, [_src(calls=0)])
    s = r["sources"][0]
    assert s["circuit_state"] == "unknown"
    assert s["success_rate_1h"] is None
    assert s["avg_latency_1h"] is None


def test_time_window_domain_uses_freshness_rule_budget(calc):
    # basic_info CN: time_window 24h → 25h 前更新即 stale
    old25 = (NOW - timedelta(hours=25)).isoformat()
    r = calc.evaluate("CN", "basic_info", 100, old25, True, [_src()], now=NOW)
    assert r["status"] == "stale"
    assert r["freshness"]["budget_hours"] == 24.0


def test_hk_trading_day_budget_overridden_to_96h(calc):
    r = calc.evaluate("HK", "daily_quotes", 100, OLD, True, [_src()], now=NOW)
    assert r["freshness"]["budget_hours"] == 96.0


def test_summarize_market_levels(calc):
    domains = [
        {"status": "healthy"},
        {"status": "degraded"},
        {"status": "no_data"},
        {"status": "unknown"},
    ]
    s = calc.summarize(domains)
    assert s["overall"] == "partial_outage"  # no_data 计入 problem
    assert s["healthy_domains"] == 1
    assert s["warning_domains"] == 1
    assert s["problem_domains"] == 1
    assert s["unknown_domains"] == 1

    s2 = calc.summarize([{"status": "healthy"}])
    assert s2["overall"] == "all_healthy"

    s3 = calc.summarize([{"status": "unknown"}])
    assert s3["overall"] == "unknown"
