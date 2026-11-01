"""结算基准 alpha 集成测试（真实 MongoDB I/O，无 mock）。

合成指数日线（index_daily_quotes）+ 合成股票行情，手算 alpha 精确断言；
基准缺失降级 null；板块→基准映射；backfill_benchmarks 幂等。
"""

import uuid
from datetime import date, timedelta

import pytest

from app.data.storage.mongo.collections import get_collection_name
from app.services.settlement_service import get_settlement_service

pytestmark = pytest.mark.requires_db

FAKE_STOCK = "999996"   # 主板（基准=沪深300）
FAKE_BSE = "839996"     # 北交所（基准=北证50）
FAKE_INDEX_HS300 = "000300.SH"
FAKE_INDEX_BSE50 = "899050.BJ"
ALL_FAKES = [FAKE_STOCK, FAKE_BSE]
ALL_INDEXES = [FAKE_INDEX_HS300, FAKE_INDEX_BSE50]


def _task_id(prefix: str) -> str:
    return f"test-bench-{prefix}-{uuid.uuid4().hex[:8]}"


def _summary(signal: str, confidence: float = 75.0) -> dict:
    return {
        "final_signal": signal,
        "model_confidence": confidence,
        "key_indicators": {},
        "analysis_summary": "基本面与市场结构共振，短线动能占优。",
    }


async def _seed_quote(db, symbol: str, trade_date: str, open_, close, pre_close):
    await db[get_collection_name("daily_quotes", "CN")].update_one(
        {"symbol": symbol, "trade_date": trade_date},
        {
            "$set": {
                "symbol": symbol,
                "trade_date": trade_date,
                "period": "daily",
                "open": open_,
                "high": max(open_, close) + 0.08,
                "low": min(open_, close) - 0.05,
                "close": close,
                "pre_close": pre_close,
                "change": round(close - pre_close, 2),
                "pct_chg": round((close - pre_close) / pre_close * 100, 2),
                "volume": 1_000_000.0,
                "amount": 10_000_000.0,
            }
        },
        upsert=True,
    )


async def _seed_rising(db, symbol: str, days: list, start_price: float = 10.0) -> dict:
    """稳步上涨行情：返回首日开盘与各日收盘。"""
    price = start_price
    prev = round(start_price - 0.05, 2)
    closes: dict = {}
    for d in days:
        await _seed_quote(db, symbol, d, price, round(price + 0.04, 2), prev)
        closes[d] = round(price + 0.04, 2)
        prev = closes[d]
        price = round(price + 0.06, 2)
    return {"first_open": start_price, "closes": closes}


async def _seed_index(db, symbol: str, trade_date: str, open_, close):
    await db[get_collection_name("index_quotes", "CN")].update_one(
        {"symbol": symbol, "trade_date": trade_date},
        {
            "$set": {
                "symbol": symbol,
                "trade_date": trade_date,
                "open": open_,
                "high": max(open_, close) + 1.0,
                "low": min(open_, close) - 1.0,
                "close": close,
                "pre_close": open_,
                "change": round(close - open_, 4),
                "pct_chg": round((close - open_) / open_ * 100, 4),
                "volume": 1000.0,
                "amount": 10000.0,
                "data_source": "test",
            }
        },
        upsert=True,
    )


@pytest.fixture(autouse=True)
async def _cleanup(real_mongo_db):
    yield
    db = real_mongo_db
    await db["decision_settlements"].delete_many({"symbol": {"$in": ALL_FAKES}})
    for s in ALL_FAKES:
        await db[get_collection_name("daily_quotes", "CN")].delete_many({"symbol": s})
    for s in ALL_INDEXES:
        await db[get_collection_name("index_quotes", "CN")].delete_many({"symbol": s})


@pytest.fixture
async def trade_days(real_mongo_db):
    from app.data.storage.mongo.repositories.trade_calendar_repo import TradeCalendarRepo

    db = real_mongo_db
    end = date.today()
    start = end - timedelta(days=60)
    cal_coll = db[get_collection_name("trade_calendar", "CN")]
    existing = {
        r["cal_date"]
        async for r in cal_coll.find(
            {"exchange": "SSE", "cal_date": {"$gte": start.isoformat(), "$lte": end.isoformat()}},
            {"cal_date": 1},
        )
    }
    missing = [
        {"exchange": "SSE", "cal_date": d.isoformat(), "is_open": True}
        for d in (start + timedelta(days=i) for i in range((end - start).days + 1))
        if d.weekday() < 5 and d.isoformat() not in existing
    ]
    if missing:
        await cal_coll.insert_many(missing)
    rows = await TradeCalendarRepo().get_range("SSE", "CN", start.isoformat(), end.isoformat())
    days = sorted(r["cal_date"] for r in rows if r.get("is_open"))
    assert len(days) >= 15
    return days


class TestBenchmarkAlpha:
    async def test_alpha_exact_value_buy_beats_benchmark(self, real_mongo_db, trade_days):
        """Buy 且跑赢：alpha = 股票收益 - 基准收益（手算精确断言）。"""
        db = real_mongo_db
        after = trade_days[-14:]
        decision_date = trade_days[-15]
        seeded = await _seed_rising(db, FAKE_STOCK, after)
        # 基准：入场日开盘 100 → 出场日收盘 102 = +2.0%
        await _seed_index(db, FAKE_INDEX_HS300, after[0], 100.0, 101.0)
        await _seed_index(db, FAKE_INDEX_HS300, after[6], 100.0, 102.0)

        svc = get_settlement_service()
        await svc.register_from_result(
            _task_id("a1"), "u1",
            {
                "stock_symbol": FAKE_STOCK, "market_type": "A股",
                "analysis_date": decision_date,
                "structured_summary": _summary("Buy", 80.0),
            },
        )
        await svc.settle_due()

        doc = await db["decision_settlements"].find_one({"symbol": FAKE_STOCK})
        assert doc["status"] == "settled"
        assert doc["benchmark_symbol"] == FAKE_INDEX_HS300
        assert doc["bench_entry"] == 100.0
        assert doc["bench_exit"] == 102.0
        assert doc["benchmark_return_pct"] == 2.0
        expected_ret = round(
            (seeded["closes"][after[6]] - seeded["first_open"]) / seeded["first_open"] * 100, 2
        )
        assert doc["return_pct"] == expected_ret
        assert doc["alpha_pct"] == round(expected_ret - 2.0, 2)
        assert doc["direction_hit_vs_benchmark"] is True

    async def test_alpha_negative_when_underperform(self, real_mongo_db, trade_days):
        """基准大涨跑输个股：alpha 为负，超额方向不命中。"""
        db = real_mongo_db
        after = trade_days[-14:]
        decision_date = trade_days[-15]
        await _seed_rising(db, FAKE_STOCK, after)
        # 基准暴涨：入场开盘 100 → 出场收盘 200 = +100%
        await _seed_index(db, FAKE_INDEX_HS300, after[0], 100.0, 101.0)
        await _seed_index(db, FAKE_INDEX_HS300, after[6], 100.0, 200.0)

        svc = get_settlement_service()
        await svc.register_from_result(
            _task_id("a2"), "u1",
            {
                "stock_symbol": FAKE_STOCK, "market_type": "A股",
                "analysis_date": decision_date,
                "structured_summary": _summary("Buy", 70.0),
            },
        )
        await svc.settle_due()
        doc = await db["decision_settlements"].find_one({"symbol": FAKE_STOCK})
        assert doc["alpha_pct"] < 0
        assert doc["direction_hit_vs_benchmark"] is False

    async def test_benchmark_missing_degrades_to_null(self, real_mongo_db, trade_days):
        """基准数据不可得：六字段中价格系 null，主结果（settled/return_pct）不受影响。"""
        db = real_mongo_db
        after = trade_days[-14:]
        decision_date = trade_days[-15]
        seeded = await _seed_rising(db, FAKE_STOCK, after)  # 不种指数

        svc = get_settlement_service()
        await svc.register_from_result(
            _task_id("a3"), "u1",
            {
                "stock_symbol": FAKE_STOCK, "market_type": "A股",
                "analysis_date": decision_date,
                "structured_summary": _summary("Sell", 60.0),
            },
        )
        await svc.settle_due()
        doc = await db["decision_settlements"].find_one({"symbol": FAKE_STOCK})
        assert doc["status"] == "settled"
        assert doc["return_pct"] is not None
        # 结算时基准数据不可得：六字段全 None（含 symbol——由 backfill 补标记）
        assert doc["benchmark_symbol"] is None
        assert doc["bench_entry"] is None
        assert doc["alpha_pct"] is None
        assert doc["direction_hit_vs_benchmark"] is None

    async def test_board_mapping_bse(self, real_mongo_db, trade_days):
        """北交所标的映射北证50（899050.BJ），不是沪深300。"""
        db = real_mongo_db
        after = trade_days[-14:]
        decision_date = trade_days[-15]
        await _seed_rising(db, FAKE_BSE, after)
        await _seed_index(db, FAKE_INDEX_BSE50, after[0], 100.0, 101.0)
        await _seed_index(db, FAKE_INDEX_BSE50, after[6], 100.0, 103.0)

        svc = get_settlement_service()
        await svc.register_from_result(
            _task_id("a4"), "u1",
            {
                "stock_symbol": FAKE_BSE, "market_type": "A股",
                "analysis_date": decision_date,
                "structured_summary": _summary("Buy", 70.0),
            },
        )
        await svc.settle_due()
        doc = await db["decision_settlements"].find_one({"symbol": FAKE_BSE})
        assert doc["benchmark_symbol"] == FAKE_INDEX_BSE50
        assert doc["benchmark_return_pct"] == 3.0

    async def test_backfill_benchmarks_idempotent(self, real_mongo_db, trade_days):
        """先结算（无指数）→ 种指数 → 回填补齐 → 二次回填 0 条。"""
        db = real_mongo_db
        after = trade_days[-14:]
        decision_date = trade_days[-15]
        seeded = await _seed_rising(db, FAKE_STOCK, after)

        svc = get_settlement_service()
        task_id = _task_id("a5")
        await svc.register_from_result(
            task_id, "u1",
            {
                "stock_symbol": FAKE_STOCK, "market_type": "A股",
                "analysis_date": decision_date,
                "structured_summary": _summary("Buy", 65.0),
            },
        )
        await svc.settle_due()

        # 结算时无指数 → 价格字段 null
        doc = await db["decision_settlements"].find_one({"task_id": task_id})
        assert doc["alpha_pct"] is None

        # 种指数后回填
        await _seed_index(db, FAKE_INDEX_HS300, after[0], 100.0, 101.0)
        await _seed_index(db, FAKE_INDEX_HS300, after[6], 100.0, 102.0)
        updated = await svc.backfill_benchmarks()
        assert updated >= 1
        doc = await db["decision_settlements"].find_one({"task_id": task_id})
        assert doc["bench_entry"] == 100.0
        assert doc["bench_exit"] == 102.0
        expected_ret = round(
            (seeded["closes"][after[6]] - seeded["first_open"]) / seeded["first_open"] * 100, 2
        )
        assert doc["alpha_pct"] == round(expected_ret - 2.0, 2)

        # 幂等：全部记录已带 benchmark_symbol，无新增
        updated_again = await svc.backfill_benchmarks()
        assert updated_again == 0

    async def test_scorecard_alpha_aggregation(self, real_mongo_db, trade_days):
        """记分卡 alpha 聚合：只计基准可得样本，样本数单独透出。"""
        db = real_mongo_db
        after = trade_days[-14:]
        decision_date = trade_days[-15]
        await _seed_rising(db, FAKE_STOCK, after)
        await _seed_index(db, FAKE_INDEX_HS300, after[0], 100.0, 101.0)
        await _seed_index(db, FAKE_INDEX_HS300, after[6], 100.0, 102.0)

        svc = get_settlement_service()
        # 一条 Buy（跑赢）+ 一条 Sell（跑输——上涨行情 Sell 的 alpha<0 为不命中）
        for i, (signal, conf) in enumerate([("Buy", 85.0), ("Sell", 65.0)]):
            await svc.register_from_result(
                _task_id(f"sc{i}"), "u1",
                {
                    "stock_symbol": FAKE_STOCK, "market_type": "A股",
                    "analysis_date": decision_date,
                    "structured_summary": _summary(signal, conf),
                },
            )
        await svc.settle_due()

        card = await svc.get_scorecard(channel="online", symbol=FAKE_STOCK)
        assert card.alpha_count == 2
        assert card.benchmark_hit_rate == 0.5  # Buy 跑赢命中、Sell 跑输不命中
        assert card.avg_alpha_pct is not None
        assert card.by_signal and all(s.avg_alpha_pct is not None for s in card.by_signal)
        assert card.trend and card.trend[-1].avg_alpha_pct is not None
