"""Recommendation diagnostics and persistence: pure logic + real MongoDB only.

No model calls, external market requests, patched functions or simulated storage.
"""

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.data.core.interface import DataInterface
from app.data.factors.strategy_config import get_factor_groups, get_strategies
from app.data.storage.mongo.collections import get_collection_name
from app.data.storage.mongo.repositories.factor_scores_repo import FactorScoresRepo
from app.data.storage.mongo.repositories.screening_recommendations_repo import (
    ScreeningRecommendationsRepo,
)
from app.services.screening.strategy_service import (
    StrategyService,
    expected_completed_trade_date,
    factor_batch_fingerprint,
    is_finite_number,
    snapshot_is_stale,
    strategy_data_quality,
)


def _strategy(strategy_id="volume_breakout"):
    return next(s for s in get_strategies() if s["id"] == strategy_id)


def _row(symbol="TESTQUALITY001", **updates):
    values = {field: 1.0 for group in get_factor_groups().values() for field in group}
    return {**values, "symbol": symbol, "trade_date": "2098-01-02",
            "bias_ma20": 3.0, "turnover_amp": 2.0, "macd_golden_days": 3,
            "score_short_term": 80.0, "score_balanced": 70.0, "score_value": 60.0,
            **updates}


@pytest.mark.parametrize("value", [None, True, False, "0", "NaN", float("nan"), float("inf"), -float("inf")])
def test_invalid_numbers_are_missing(value):
    assert not is_finite_number(value)
    row = _row(turnover_amp=value)
    quality = strategy_data_quality([row], _strategy())
    assert quality["status"] == "insufficient"
    assert quality["eligible_count"] == 0
    assert "turnover_amp" in quality["missing_fields"]
    assert not StrategyService._match(row, [{"field": "turnover_amp", "op": "!=", "value": 1}])


def test_zero_is_available_and_not_missing():
    assert is_finite_number(0)
    quality = strategy_data_quality([_row(ret_5d=0)], _strategy())
    assert quality["status"] == "complete"
    assert quality["field_coverage"]["ret_5d"] == {"available": 1, "total": 1}


def test_score_contributors_are_checked_not_only_filter_fields():
    quality = strategy_data_quality([_row(main_inflow_5d=None)], _strategy())
    assert quality["status"] == "partial"
    assert quality["eligible_count"] == 1
    assert "main_inflow_5d" in quality["missing_fields"]
    assert quality["field_coverage"]["main_inflow_5d"]["available"] == 0


def test_partial_filter_coverage_and_joint_eligibility():
    rows = [_row(turnover_amp=None), _row("TESTQUALITY002", bias_ma20=None)]
    quality = strategy_data_quality(rows, _strategy())
    assert quality["status"] == "insufficient"
    assert quality["eligible_count"] == 0
    assert quality["total_universe"] == 2
    assert {"bias_ma20", "turnover_amp"} <= set(quality["partial_fields"])


def test_complete_zero_matches_differs_from_missing_inputs():
    svc = StrategyService()
    result = svc._evaluate_strategy([_row(bias_ma20=-1)], "2098-01-02", _strategy())
    assert result["total"] == 0
    assert result["data_quality"]["status"] == "complete"
    result = svc._evaluate_strategy([_row(bias_ma20=None)], "2098-01-02", _strategy())
    assert result["total"] == 0
    assert result["data_quality"]["status"] == "insufficient"


def test_invalid_score_is_not_ranked_or_serialized():
    result = StrategyService()._evaluate_strategy(
        [_row(score_short_term=float("nan")), _row("TESTQUALITY002", score_value=float("inf"))],
        "2098-01-02", _strategy())
    assert result["total"] == 1
    assert result["items"][0]["score_value"] is None
    assert result["data_quality"]["status"] == "partial"


def test_batch_fingerprint_is_stable_but_not_blind_to_input_changes():
    first, second = _row(), _row("TESTQUALITY002")
    fingerprint = factor_batch_fingerprint([first, second])
    assert fingerprint == factor_batch_fingerprint([{**second, "updated_at": "later"}, first])
    assert fingerprint != factor_batch_fingerprint([first, {**second, "debt_ratio": 80}])
    assert factor_batch_fingerprint([_row(roe=float("nan"))]) == factor_batch_fingerprint([_row(roe=None)])


@pytest.mark.parametrize("hour,expected", [(10, "2026-09-30"), (15, "2026-10-08"), (21, "2026-10-08")])
def test_expected_date_respects_long_holiday_and_close(hour, expected):
    calendar = [{"cal_date": "2026-09-30", "is_open": 1}]
    calendar += [{"cal_date": f"2026-10-{day:02}", "is_open": 0} for day in range(1, 8)]
    calendar += [{"cal_date": "2026-10-08", "is_open": 1}]
    current = datetime(2026, 10, 8, hour, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert expected_completed_trade_date(calendar, current) == expected


def test_missing_or_conflicting_calendar_does_not_guess_weekdays():
    current = datetime(2026, 10, 8, 21, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert expected_completed_trade_date([{"cal_date": "2026-09-30", "is_open": 1}], current) is None
    assert expected_completed_trade_date([
        {"cal_date": "2026-10-08", "is_open": 1},
        {"cal_date": "2026-10-08", "is_open": 0},
    ], current) is None


@pytest.mark.parametrize("as_of,expected,refresh,result", [
    ("2026-10-09", "2026-10-08", False, True),
    ("2026-09-30", "2026-10-08", False, True),
    ("2026-10-08", "2026-10-08", False, False),
    ("2026-10-08", "2026-10-08", True, True),
    ("2026-10-08", None, False, None),
])
def test_future_and_past_dates_are_not_fresh(as_of, expected, refresh, result):
    assert snapshot_is_stale(as_of, expected, refresh) is result


def test_auto_insight_prompt_uses_only_stored_recommendation_snapshot():
    from app.services.screening.insight_service import ScreeningInsightService

    doc = {"trade_date": "2026-09-30", "items": [{
        "symbol": "TESTQUALITY001", "name": "快照", "score_short_term": 80,
        "factors": {"ret_5d": 2, "roe": 17},
    }]}
    rows = ScreeningInsightService._recommendation_rows(doc)
    # The snapshot helper owns a copy; no mutable storage read or item alias.
    doc["items"][0]["factors"]["roe"] = 99
    assert rows[0]["roe"] == 17
    prompt = ScreeningInsightService._build_prompt(rows)
    assert "2026-09-30" in prompt and "roe=17" in prompt and "roe=99" not in prompt


@pytest.fixture
async def quality_db(real_mongo_db):
    factors = real_mongo_db[get_collection_name("factor_scores", "CN")]
    recommendations = real_mongo_db[get_collection_name("screening_recommendations", "CN")]
    query = {"trade_date": "2098-01-02"}
    await factors.delete_many({"symbol": {"$regex": "^TESTQUALITY"}})
    await recommendations.delete_many(query)
    await real_mongo_db.system_configs.delete_many({"config_name": "screening_quality_test"})
    await real_mongo_db.system_configs.insert_one({
        "config_name": "screening_quality_test", "config_type": "system",
        "version": 9999999, "is_active": True, "llm_configs": [],
        "system_settings": {"screening_daily_insight_enabled": False},
    })
    yield real_mongo_db
    await factors.delete_many({"symbol": {"$regex": "^TESTQUALITY"}})
    await recommendations.delete_many(query)
    await real_mongo_db.system_configs.delete_many({"config_name": "screening_quality_test"})


@pytest.mark.requires_db
async def test_get_diagnostics_is_read_only_and_generation_uses_one_batch(quality_db):
    await FactorScoresRepo().upsert_many([_row()], "CN")
    coll = quality_db[get_collection_name("screening_recommendations", "CN")]
    svc = StrategyService()
    before = await coll.count_documents({})
    daily = await svc.get_daily("volume_breakout")
    assert daily["status"] == "not_generated"
    assert daily["trade_date"] is None
    assert daily["factor_trade_date"] == "2098-01-02"
    assert await coll.count_documents({}) == before
    result = await svc.generate_daily_recommendations()
    assert result["strategies_written"] == 6
    daily = await svc.get_daily("volume_breakout")
    assert daily["status"] == "ready"
    assert daily["recommendation_needs_refresh"] is False
    assert daily["strategies"][0]["data_quality"]["status"] == "complete"


@pytest.mark.requires_db
async def test_same_date_input_change_is_stale_until_regenerated(quality_db):
    await FactorScoresRepo().upsert_many([_row()], "CN")
    svc = StrategyService()
    await svc.generate_daily_recommendations()
    await FactorScoresRepo().upsert_many([_row(roe=17)], "CN")
    daily = await svc.get_daily("volume_breakout")
    assert daily["trade_date"] == daily["factor_trade_date"]
    assert daily["recommendation_needs_refresh"] is True
    assert daily["is_stale"] is True


@pytest.mark.requires_db
async def test_complete_recalculation_token_does_not_change_content_fingerprint(quality_db):
    repo = FactorScoresRepo()
    interface = DataInterface.get_instance()
    filters = {"trade_date": "2098-01-02"}
    # This complete-date publisher must never replace another test's rows.
    coll = quality_db[get_collection_name("factor_scores", "CN")]
    assert await coll.count_documents(filters) == 0
    rows = [_row(), _row("TESTQUALITY002")]
    await repo.replace_complete_date(rows, "CN", "2098-01-02")
    first = (await interface.screen("CN", "factor_scores", filters=filters, limit=0))["items"]
    original_hash = factor_batch_fingerprint(first)
    await StrategyService().generate_daily_recommendations()

    await repo.replace_complete_date(rows, "CN", "2098-01-02")
    second = (await interface.screen("CN", "factor_scores", filters=filters, limit=0))["items"]
    assert {row["_calculation_id"] for row in first} != {row["_calculation_id"] for row in second}
    assert factor_batch_fingerprint(second) == original_hash
    assert (await StrategyService().get_daily("volume_breakout"))["recommendation_needs_refresh"] is False

    await repo.replace_complete_date([rows[0], {**rows[1], "roe": 19}], "CN", "2098-01-02")
    changed = (await interface.screen("CN", "factor_scores", filters=filters, limit=0))["items"]
    assert factor_batch_fingerprint(changed) != original_hash
    assert (await StrategyService().get_daily("volume_breakout"))["recommendation_needs_refresh"] is True


@pytest.mark.requires_db
@pytest.mark.parametrize("legacy", [False, True])
async def test_unchanged_regeneration_preserves_paid_commentary(quality_db, legacy):
    await FactorScoresRepo().upsert_many([_row()], "CN")
    svc = StrategyService()
    await svc.generate_daily_recommendations()
    coll = quality_db[get_collection_name("screening_recommendations", "CN")]
    key = {"strategy_id": "volume_breakout", "trade_date": "2098-01-02"}
    update = {"$set": {"items.0.insight": "已完成的短评", "insight_status": "done",
                       "insight_generated_at": "original-time"}}
    if legacy:
        update["$unset"] = {"recommendation_fingerprint": ""}
    await coll.update_one(key, update)
    await svc.generate_daily_recommendations()
    doc = await coll.find_one(key)
    assert doc["insight_status"] == "done"
    assert doc["items"][0]["insight"] == "已完成的短评"
    assert doc["insight_generated_at"] == "original-time"
    assert await coll.count_documents(key) == 1
    await FactorScoresRepo().upsert_many([_row(score_short_term=90)], "CN")
    await svc.generate_daily_recommendations()
    doc = await coll.find_one(key)
    assert doc["insight_status"] == "none"
    assert "insight" not in doc["items"][0]
    assert "insight_generated_at" not in doc


@pytest.mark.requires_db
async def test_insight_claim_is_atomic_and_cannot_overwrite_new_snapshot(quality_db):
    await FactorScoresRepo().upsert_many([_row()], "CN")
    await StrategyService().generate_daily_recommendations()
    repo = ScreeningRecommendationsRepo()
    doc = await repo.get_by_strategy_and_date("CN", "volume_breakout", "2098-01-02")
    claims = await asyncio.gather(*(repo.claim_insight(doc, "CN") for _ in range(4)))
    assert claims.count(True) == 1
    await FactorScoresRepo().upsert_many([_row(score_short_term=90)], "CN")
    await StrategyService().generate_daily_recommendations()
    assert not await repo.finish_insight({**doc, "insight_status": "done"}, "CN")
    latest = await repo.get_by_strategy_and_date("CN", "volume_breakout", "2098-01-02")
    assert latest["insight_status"] == "none"
    assert latest["items"][0]["score"] == 90


@pytest.mark.requires_db
async def test_legacy_daily_quality_is_unknown_without_rewriting_record(quality_db):
    repo = ScreeningRecommendationsRepo()
    await repo.upsert_daily({"strategy_id": "legacy", "trade_date": "2098-01-02", "items": []}, "CN")
    result = await StrategyService().get_daily("legacy")
    assert result["strategies"][0]["data_quality"]["status"] == "unknown"
    original = await repo.get_by_strategy_and_date("CN", "legacy", "2098-01-02")
    assert "data_quality" not in original


@pytest.mark.requires_db
async def test_real_scheduled_job_generates_without_paid_insight(quality_db):
    from app.worker.screening_jobs import run_screening_daily_recommendations

    await FactorScoresRepo().upsert_many([_row()], "CN")
    result = await run_screening_daily_recommendations()
    assert result["status"] == "ready"
    assert result["strategies_written"] == 6
    assert result["insight"] is None
    doc = await ScreeningRecommendationsRepo().get_by_strategy_and_date(
        "CN", "volume_breakout", "2098-01-02")
    assert doc["insight_status"] == "none"


@pytest.mark.requires_db
async def test_string_false_does_not_enable_paid_insight(quality_db):
    from app.services.screening.insight_service import ScreeningInsightService

    await quality_db.system_configs.update_one(
        {"config_name": "screening_quality_test"},
        {"$set": {"system_settings.screening_daily_insight_enabled": "false"}})
    assert await ScreeningInsightService().run_daily_auto_if_enabled() is None


@pytest.mark.requires_db
@pytest.mark.parametrize("status", ["done", "failed", "pending"])
async def test_attempted_auto_insight_is_not_charged_again(quality_db, status):
    from app.services.screening.insight_service import ScreeningInsightService

    await FactorScoresRepo().upsert_many([_row()], "CN")
    await StrategyService().generate_daily_recommendations()
    await quality_db[get_collection_name("screening_recommendations", "CN")].update_one(
        {"strategy_id": "volume_breakout", "trade_date": "2098-01-02"},
        {"$set": {"insight_status": status}})
    await quality_db.system_configs.update_one(
        {"config_name": "screening_quality_test"},
        {"$set": {"system_settings.screening_daily_insight_enabled": True}})
    result = await ScreeningInsightService().run_daily_auto_if_enabled()
    assert result == {"status": "skipped", "reason": "already_attempted"}
