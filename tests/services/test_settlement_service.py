"""结算服务端到端测试（真实 MongoDB I/O，无 mock）。

行情种在假标的（9999x/3099x/8399x 等未上市代码）上，不与真实同步数据冲突；
清理只按假标的过滤，绝不触碰真实行情。测试库（tradingagents_test）的 trade_calendar
无同步数据，日历为空时补种合成 SSE 工作日（只补缺失日期，不动已有行）。
"""

import uuid
from datetime import date, timedelta

import pytest

from app.data.storage.mongo.collections import get_collection_name
from app.services.settlement_service import get_settlement_service

pytestmark = pytest.mark.requires_db

# 每个测试用独立假标的，聚合断言按 symbol 隔离
FAKE_REGISTER = "999990"   # 主板（登记用）
FAKE_SETTLE = "999991"     # 主板（正常结算）
FAKE_SELL = "999992"       # 主板（方向错）
FAKE_HOLD = "999993"       # 主板（Hold 口径）
FAKE_LIMIT = "999994"      # 主板（一字涨停）
FAKE_BSE = "839999"        # 北交所（30% 幅差）
FAKE_SUSP = "309999"       # 创业板（停牌顺延）
FAKE_TODAY = "999995"      # 到期日=当日（当日 bar 排除）
FAKE_SCORE = "999981"      # 记分卡聚合
FAKE_LIST = "999982"       # 列表/按任务查询
FAKE_MID = "999983"        # 中线档（20 交易日）
FAKE_LONG = "999984"       # 长线档（60 交易日）
ALL_FAKES = [
    FAKE_REGISTER, FAKE_SETTLE, FAKE_SELL, FAKE_HOLD, FAKE_LIMIT,
    FAKE_BSE, FAKE_SUSP, FAKE_TODAY, FAKE_SCORE, FAKE_LIST,
    FAKE_MID, FAKE_LONG,
]


def _task_id(prefix: str) -> str:
    return f"test-settle-{prefix}-{uuid.uuid4().hex[:8]}"


def _summary(signal: str = "Buy", confidence: float = 75.0, fail_text: str = "") -> dict:
    return {
        "final_signal": signal,
        "model_confidence": confidence,
        "key_indicators": {"entry_price": "10", "target_price": "11", "stop_loss": "9"},
        "analysis_summary": fail_text or "基本面与市场结构共振，短线动能占优。",
    }


async def _seed_quote(db, symbol: str, trade_date: str, open_, high, low, close, pre_close):
    await db[get_collection_name("daily_quotes", "CN")].update_one(
        {"symbol": symbol, "trade_date": trade_date},
        {
            "$set": {
                "symbol": symbol,
                "trade_date": trade_date,
                "period": "daily",
                "open": open_,
                "high": high,
                "low": low,
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


async def _seed_rising_quotes(db, symbol: str, days: list, start_price: float = 10.0) -> dict:
    """在给定交易日序列上种一段稳步上涨行情（无涨跌停、有日内波动）。

    返回 {"first_open": 首日开盘价, "closes": {trade_date: 收盘价}}。
    """
    price = start_price
    prev = round(start_price - 0.05, 2)
    closes: dict = {}
    for d in days:
        await _seed_quote(db, symbol, d, price, round(price + 0.08, 2), round(price - 0.05, 2),
                          round(price + 0.04, 2), prev)
        closes[d] = round(price + 0.04, 2)
        prev = closes[d]
        price = round(price + 0.06, 2)
    return {"first_open": start_price, "closes": closes}


@pytest.fixture(autouse=True)
async def _cleanup(real_mongo_db):
    yield
    db = real_mongo_db
    await db["decision_settlements"].delete_many({"symbol": {"$in": ALL_FAKES}})
    quotes_coll = get_collection_name("daily_quotes", "CN")
    for s in ALL_FAKES:
        await db[quotes_coll].delete_many({"symbol": s})


@pytest.fixture
async def trade_days(real_mongo_db):
    """最近交易日序列（升序）：测试库日历为空时补种合成 SSE 工作日，保证结算窗口可用。

    只插入集合中不存在的日期（不覆盖已有行，含节假日休市行）；测试库无真实日历，
    补种行留在库中供后续测试复用，不影响任何真实数据。
    """
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
    assert len(days) >= 15, "trade_calendar 近 60 日数据不足"
    return days


class TestRegister:
    async def test_register_from_summary(self, real_mongo_db):
        db = real_mongo_db
        task_id = _task_id("reg")
        result = {
            "stock_symbol": FAKE_REGISTER,
            "market_type": "A股",
            "analysis_date": "2026-10-20",
            "structured_summary": _summary("Buy", 75.0),
        }
        registered = await get_settlement_service().register_from_result(task_id, "u1", result)
        assert registered == task_id
        doc = await db["decision_settlements"].find_one({"task_id": task_id})
        assert doc is not None
        assert doc["symbol"] == FAKE_REGISTER
        assert doc["market"] == "CN"
        assert doc["signal"] == "Buy"
        assert doc["stated_confidence"] == 75.0
        assert doc["status"] == "pending"
        assert doc["channel"] == "online"
        assert doc["board"] == "主板"
        assert doc["signal_source"] == "summary"

    async def test_register_idempotent(self, real_mongo_db):
        db = real_mongo_db
        task_id = _task_id("reg2")
        result = {
            "stock_symbol": FAKE_REGISTER,
            "market_type": "A股",
            "structured_summary": _summary("Buy", 60.0),
        }
        svc = get_settlement_service()
        await svc.register_from_result(task_id, "u1", result)
        await svc.register_from_result(task_id, "u1", result)
        count = await db["decision_settlements"].count_documents({"task_id": task_id})
        assert count == 1

    async def test_register_skips_placeholder_signature(self, real_mongo_db):
        # 兜底包签名：Hold + 置信度 0 → 不登记
        task_id = _task_id("skip1")
        result = {
            "stock_symbol": FAKE_REGISTER,
            "market_type": "A股",
            "structured_summary": _summary("Hold", 0),
        }
        assert await get_settlement_service().register_from_result(task_id, "u1", result) is None
        assert await real_mongo_db["decision_settlements"].find_one({"task_id": task_id}) is None

    async def test_register_skips_failure_text(self, real_mongo_db):
        task_id = _task_id("skip2")
        result = {
            "stock_symbol": FAKE_REGISTER,
            "market_type": "A股",
            "structured_summary": _summary("Buy", 50.0, fail_text="系统错误：无法生成分析摘要"),
        }
        assert await get_settlement_service().register_from_result(task_id, "u1", result) is None

    async def test_register_falls_back_to_decision(self, real_mongo_db):
        db = real_mongo_db
        task_id = _task_id("fb")
        result = {
            "stock_symbol": FAKE_REGISTER,
            "market_type": "A股",
            "structured_summary": {},
            "decision": {"action": "观望", "confidence": 0.7},
        }
        assert await get_settlement_service().register_from_result(task_id, "u1", result) == task_id
        doc = await db["decision_settlements"].find_one({"task_id": task_id})
        assert doc["signal"] == "Hold"
        assert doc["stated_confidence"] == 70.0
        assert doc["signal_source"] == "decision"


class TestSettle:
    async def test_settle_buy_hit(self, real_mongo_db, trade_days):
        db = real_mongo_db
        task_id = _task_id("buy")
        decision_date = trade_days[-15]
        after = trade_days[-14:]           # 决策日后的交易日序列
        seeded = await _seed_rising_quotes(db, FAKE_SETTLE, after)
        result = {
            "stock_symbol": FAKE_SETTLE,
            "market_type": "A股",
            "analysis_date": decision_date,
            "structured_summary": _summary("Buy", 80.0),
        }
        svc = get_settlement_service()
        await svc.register_from_result(task_id, "u1", result)
        stats = await svc.settle_due()
        assert stats["settled"] >= 1

        entry_price = seeded["first_open"]
        exit_price = seeded["closes"][after[6]]
        doc = await db["decision_settlements"].find_one({"task_id": task_id})
        assert doc["status"] == "settled"
        assert doc["entry_date"] == after[0]          # T+1 开盘入场
        assert doc["entry_price"] == entry_price
        assert doc["exit_date"] == after[6]           # 第 7 个交易日收盘
        assert doc["exit_price"] == exit_price
        expected_ret = round((exit_price - entry_price) / entry_price * 100, 2)
        assert doc["return_pct"] == expected_ret
        assert doc["actual_direction"] == "up"
        assert doc["direction_hit"] is True
        assert doc["error_type"] is None

    async def test_settle_sell_direction_wrong(self, real_mongo_db, trade_days):
        db = real_mongo_db
        task_id = _task_id("sell")
        decision_date = trade_days[-15]
        after = trade_days[-14:]
        await _seed_rising_quotes(db, FAKE_SELL, after)
        result = {
            "stock_symbol": FAKE_SELL,
            "market_type": "A股",
            "analysis_date": decision_date,
            "structured_summary": _summary("Sell", 70.0),
        }
        svc = get_settlement_service()
        await svc.register_from_result(task_id, "u1", result)
        await svc.settle_due()
        doc = await db["decision_settlements"].find_one({"task_id": task_id})
        assert doc["status"] == "settled"
        assert doc["direction_hit"] is False
        assert doc["error_type"] == "direction_wrong"

    async def test_settle_hold_excluded_from_hit(self, real_mongo_db, trade_days):
        db = real_mongo_db
        task_id = _task_id("hold")
        decision_date = trade_days[-15]
        after = trade_days[-14:]
        await _seed_rising_quotes(db, FAKE_HOLD, after)
        result = {
            "stock_symbol": FAKE_HOLD,
            "market_type": "A股",
            "analysis_date": decision_date,
            "structured_summary": _summary("Hold", 55.0, fail_text="持有观察，等待突破。"),
        }
        svc = get_settlement_service()
        await svc.register_from_result(task_id, "u1", result)
        await svc.settle_due()
        doc = await db["decision_settlements"].find_one({"task_id": task_id})
        assert doc["status"] == "settled"
        assert doc["direction_hit"] is None
        assert doc["error_type"] is None

    async def test_settle_unfillable_on_limit_up_board(self, real_mongo_db, trade_days):
        db = real_mongo_db
        task_id = _task_id("limit")
        decision_date = trade_days[-15]
        entry_day = trade_days[-14]
        # 主板一字涨停：昨收 10 → 涨停 11.0，开盘即封且全天无波动
        await _seed_quote(db, FAKE_LIMIT, entry_day, 11.0, 11.0, 11.0, 11.0, 10.0)
        result = {
            "stock_symbol": FAKE_LIMIT,
            "market_type": "A股",
            "analysis_date": decision_date,
            "structured_summary": _summary("Buy", 85.0),
        }
        svc = get_settlement_service()
        await svc.register_from_result(task_id, "u1", result)
        await svc.settle_due()
        doc = await db["decision_settlements"].find_one({"task_id": task_id})
        assert doc["status"] == "unfillable"
        assert doc["error_type"] == "unfillable"
        assert doc["failure_reason"] == "一字涨停无法买入"
        assert doc["entry_date"] == entry_day
        assert doc["entry_price"] == 11.0

    async def test_settle_bse_30_percent_limit(self, real_mongo_db, trade_days):
        db = real_mongo_db
        task_id = _task_id("bse")
        decision_date = trade_days[-15]
        entry_day = trade_days[-14]
        # 北交所 ±30%：昨收 10 → 涨停 13.0 一字
        await _seed_quote(db, FAKE_BSE, entry_day, 13.0, 13.0, 13.0, 13.0, 10.0)
        result = {
            "stock_symbol": FAKE_BSE,
            "market_type": "A股",
            "analysis_date": decision_date,
            "structured_summary": _summary("Buy", 80.0),
        }
        svc = get_settlement_service()
        await svc.register_from_result(task_id, "u1", result)
        await svc.settle_due()
        doc = await db["decision_settlements"].find_one({"task_id": task_id})
        assert doc["status"] == "unfillable"
        assert doc["board"] == "北交所"

    async def test_settle_entry_postponed_by_suspension(self, real_mongo_db, trade_days):
        db = real_mongo_db
        task_id = _task_id("susp")
        decision_date = trade_days[-15]
        after = trade_days[-14:]
        # 首个交易日停牌（无行情），次一交易日复牌 → 入场顺延
        await _seed_rising_quotes(db, FAKE_SUSP, after[1:])
        result = {
            "stock_symbol": FAKE_SUSP,
            "market_type": "A股",
            "analysis_date": decision_date,
            "structured_summary": _summary("Buy", 70.0),
        }
        svc = get_settlement_service()
        await svc.register_from_result(task_id, "u1", result)
        await svc.settle_due()
        doc = await db["decision_settlements"].find_one({"task_id": task_id})
        assert doc["status"] == "settled"
        assert doc["entry_date"] == after[1]
        assert doc["exit_date"] == after[7]          # 自决策日起第 7 个交易日（停牌顺延后）
        assert doc["direction_hit"] is True

    async def test_settle_excludes_today_unfinalized_bar(self, real_mongo_db, trade_days):
        """到期日恰为市场时区当日：当日 bar 可能是盘中半日行情，不参与结算，顺延次日。"""
        from datetime import datetime

        from app.data.core.market import get_market_timezone

        db = real_mongo_db
        task_id = _task_id("today")
        decision_date = trade_days[-8]
        after = trade_days[-7:]                 # 出场落在 after[6] = 序列最后一日
        await _seed_rising_quotes(db, FAKE_TODAY, after)
        result = {
            "stock_symbol": FAKE_TODAY,
            "market_type": "A股",
            "analysis_date": decision_date,
            "structured_summary": _summary("Buy", 70.0),
        }
        svc = get_settlement_service()
        await svc.register_from_result(task_id, "u1", result)
        await svc.settle_due()
        doc = await db["decision_settlements"].find_one({"task_id": task_id})

        cn_today = datetime.now(get_market_timezone("CN")).strftime("%Y-%m-%d")
        if trade_days[-1] == cn_today:
            # 最后一日是当日：被排除，记录保持 pending 待次日结算
            assert doc["status"] == "pending"
        else:
            assert doc["status"] == "settled"
            assert doc["exit_date"] == trade_days[-1]


class TestAggregate:
    async def test_scorecard_by_symbol(self, real_mongo_db, trade_days):
        db = real_mongo_db
        after = trade_days[-14:]
        decision_date = trade_days[-15]
        await _seed_rising_quotes(db, FAKE_SCORE, after)
        svc = get_settlement_service()
        # 一条命中（Buy 上涨）+ 一条方向错（Sell 上涨）
        await svc.register_from_result(
            _task_id("sc1"), "u1",
            {
                "stock_symbol": FAKE_SCORE, "market_type": "A股",
                "analysis_date": decision_date,
                "structured_summary": _summary("Buy", 85.0),
            },
        )
        await svc.register_from_result(
            _task_id("sc2"), "u1",
            {
                "stock_symbol": FAKE_SCORE, "market_type": "A股",
                "analysis_date": decision_date,
                "structured_summary": _summary("Sell", 65.0),
            },
        )
        await svc.settle_due()

        card = await svc.get_scorecard(channel="online", symbol=FAKE_SCORE)
        assert card.total_registered == 2
        assert card.settled_count == 2
        assert card.hit_rate == 0.5
        assert card.hit_ci is not None and card.hit_ci["low"] <= 0.5 <= card.hit_ci["high"]
        assert card.unfillable_ratio == 0.0
        # 校准桶：85 → 80+；65 → 60-70
        buckets = {b.bucket: b for b in card.calibration}
        assert buckets["80+"].count == 1
        assert buckets["60-70"].count == 1
        assert buckets["<60"].count == 0
        assert card.trend and card.trend[-1].count >= 2
        signals = {s.signal: s for s in card.by_signal}
        assert signals["Buy"].hit_rate == 1.0
        assert signals["Sell"].hit_rate == 0.0

    async def test_list_records_and_by_task(self, real_mongo_db, trade_days):
        db = real_mongo_db
        task_id = _task_id("list")
        decision_date = trade_days[-15]
        await _seed_rising_quotes(db, FAKE_LIST, trade_days[-14:])
        svc = get_settlement_service()
        await svc.register_from_result(
            task_id, "u1",
            {
                "stock_symbol": FAKE_LIST, "market_type": "A股",
                "analysis_date": decision_date,
                "structured_summary": _summary("Buy", 70.0),
            },
        )
        lst = await svc.list_records(symbol=FAKE_LIST, status="pending")
        assert lst.total == 1
        assert lst.items[0].task_id == task_id

        doc = await svc.get_by_task(task_id)
        assert doc is not None and doc["status"] == "pending"
        assert doc["days_remaining"] == 0   # 窗口已过第 7 个交易日，到期待结算

        await svc.settle_due()
        lst2 = await svc.list_records(symbol=FAKE_LIST, error_type="direction_wrong")
        assert lst2.total == 0   # Buy 上涨 → 命中，不产生方向错


async def _long_trade_days(db, back_days: int, forward_days: int = 0) -> list:
    """补种 [今天-back_days, 今天+forward_days] 的合成工作日日历（只插缺失），返回升序交易日。"""
    from app.data.storage.mongo.repositories.trade_calendar_repo import TradeCalendarRepo

    cal_coll = db[get_collection_name("trade_calendar", "CN")]
    today = date.today()
    start = today - timedelta(days=back_days)
    end = today + timedelta(days=forward_days)
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
    return sorted(r["cal_date"] for r in rows if r.get("is_open"))


class TestHorizon:
    """期限贯通：登记取数、按期结算、pending 不阅卷、长假 cap、分组过滤。"""

    async def test_register_takes_horizon_from_result(self, real_mongo_db):
        db = real_mongo_db
        svc = get_settlement_service()
        for horizon, expect in (("mid", 20), ("long", 60), (None, 7), ("bogus", 7)):
            task_id = _task_id(f"hz-{horizon or 'none'}")
            await svc.register_from_result(
                task_id, "u1",
                {
                    "stock_symbol": FAKE_MID, "market_type": "A股",
                    "analysis_date": "2026-10-20",
                    "structured_summary": _summary("Buy", 70.0),
                    "horizon": horizon,
                },
            )
            doc = await db["decision_settlements"].find_one({"task_id": task_id})
            assert doc["horizon_days"] == expect, f"horizon={horizon!r} 应映射 {expect}"
            await db["decision_settlements"].delete_one({"task_id": task_id})

    async def test_settle_mid_exits_on_20th_trading_day(self, real_mongo_db):
        db = real_mongo_db
        days = await _long_trade_days(db, 60)
        decision_date = days[0]
        after = days[1:]
        assert len(after) >= 22
        await _seed_rising_quotes(db, FAKE_MID, after)
        svc = get_settlement_service()
        await svc.register_from_result(
            _task_id("mid20"), "u1",
            {
                "stock_symbol": FAKE_MID, "market_type": "A股",
                "analysis_date": decision_date,
                "structured_summary": _summary("Buy", 70.0),
                "horizon": "mid",
            },
        )
        summary = await svc.settle_due()
        assert summary["settled"] >= 1
        doc = await db["decision_settlements"].find_one({"symbol": FAKE_MID})
        assert doc["status"] == "settled"
        assert doc["entry_date"] == after[0]      # T+1 开盘入场
        assert doc["exit_date"] == after[19]      # 第 20 个交易日收盘出场

    async def test_settle_long_pending_until_window_full(self, real_mongo_db):
        """长线档窗口未走满（决策日近）：pending 只计数不阅卷，剩余天数按日历推算。"""
        db = real_mongo_db
        days = await _long_trade_days(db, 40, forward_days=110)
        today = date.today().isoformat()
        past = [d for d in days if d <= today]
        decision_date = past[-10]   # 距今约 10 交易日 << 60 档窗口
        svc = get_settlement_service()
        task_id = _task_id("long-pending")
        await svc.register_from_result(
            task_id, "u1",
            {
                "stock_symbol": FAKE_LONG, "market_type": "A股",
                "analysis_date": decision_date,
                "structured_summary": _summary("Buy", 70.0),
                "horizon": "long",
            },
        )
        await svc.settle_due()
        doc = await db["decision_settlements"].find_one({"symbol": FAKE_LONG})
        assert doc["status"] == "pending"        # 窗口未满，只计数不阅卷
        out = await svc.get_by_task(task_id)
        assert out["days_remaining"] is not None and out["days_remaining"] > 0

    async def test_long_not_killed_by_legacy_90day_cap(self, real_mongo_db):
        """旧 _MAX_WAIT_DAYS=90 会把长线档误判 unfillable：决策日距今 ~125 自然日
        （>90 且 <130 cap），60 交易日行情齐 → 必须 settled。"""
        db = real_mongo_db
        days = await _long_trade_days(db, 130)
        # 从尾端回退：决策日选在约 125 自然日前（保证 <130 cap 且其后 ≥60 交易日）
        after_full = days[1:]
        assert len(after_full) >= 62
        decision_date = days[0]
        after = after_full[:60]
        await _seed_rising_quotes(db, FAKE_LONG, after)
        svc = get_settlement_service()
        await svc.register_from_result(
            _task_id("long-settle"), "u1",
            {
                "stock_symbol": FAKE_LONG, "market_type": "A股",
                "analysis_date": decision_date,
                "structured_summary": _summary("Buy", 70.0),
                "horizon": "long",
            },
        )
        await svc.settle_due()
        doc = await db["decision_settlements"].find_one({"symbol": FAKE_LONG})
        assert doc["status"] == "settled"
        assert doc["exit_date"] == after_full[59]

    async def test_scorecard_by_horizon_and_filter(self, real_mongo_db):
        """by_horizon 分桶含 pending 计数；list_records 按档过滤；旧记录落 7 桶。"""
        db = real_mongo_db
        days = await _long_trade_days(db, 60)
        decision_date = days[0]
        after = days[1:]
        assert len(after) >= 22
        await _seed_rising_quotes(db, FAKE_SCORE, after[:22])
        svc = get_settlement_service()
        # 7 档（旧式：无 horizon 字段，手工插 settled）+ 20 档 settled + 60 档 pending
        await db["decision_settlements"].insert_one({
            "task_id": _task_id("hz-legacy"), "user_id": "u1", "symbol": FAKE_SCORE,
            "stock_name": None, "market": "CN", "decision_date": decision_date,
            "signal": "Buy", "stated_confidence": 70.0, "key_prices": {},
            "horizon_days": 7, "channel": "online", "status": "settled",
            "board": "主板", "signal_source": "summary",
            "entry_date": after[0], "entry_price": 10.0,
            "exit_date": after[6], "exit_price": 10.4,
            "return_pct": 4.0, "actual_direction": "up", "direction_hit": True,
            "error_type": None, "failure_reason": None,
        })
        await svc.register_from_result(
            _task_id("hz-mid"), "u1",
            {
                "stock_symbol": FAKE_SCORE, "market_type": "A股",
                "analysis_date": decision_date,
                "structured_summary": _summary("Buy", 70.0),
                "horizon": "mid",
            },
        )
        await svc.register_from_result(
            _task_id("hz-long"), "u1",
            {
                "stock_symbol": FAKE_SCORE, "market_type": "A股",
                "analysis_date": decision_date,
                "structured_summary": _summary("Buy", 70.0),
                "horizon": "long",
            },
        )
        await svc.settle_due()

        card = await svc.get_scorecard(channel="all", symbol=FAKE_SCORE)
        buckets = {h.horizon_days: h for h in card.by_horizon}
        assert set(buckets) == {7, 20, 60}
        assert buckets[7].count == 1 and buckets[7].hit_rate == 1.0
        assert buckets[20].count == 1 and buckets[20].hit_rate == 1.0
        assert buckets[60].pending == 1 and buckets[60].hit_rate is None

        lst = await svc.list_records(symbol=FAKE_SCORE, horizon_days=20)
        assert lst.total == 1 and lst.items[0].horizon_days == 20
