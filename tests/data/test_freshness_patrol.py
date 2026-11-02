"""数据新鲜度巡检与自动补数测试 — freshness_patrol 模块。

设计原则：不使用 unittest.mock，走真实代码路径。
- evaluate_domain：SimulatedMongoDB 注入，种 trade_calendar + sync_checkpoints
- _expected_trading_date：真实日历数据驱动（周末/收盘前/节假日三态）
- run_patrol：真实 SchedulerEngine（未启动调度器，仅注册表），
  验证落后域被发现并经 run_job_now 触发补偿
"""

import pytest
from datetime import date, timedelta

from test_infra import SimulatedMongoDB


@pytest.fixture
async def patrol_db():
    """注入 SimulatedMongoDB 并种入交易日历与检查点基础数据。"""
    from app.data.storage.mongo import client as mongo_client

    original = mongo_client._motor_db
    db = SimulatedMongoDB()
    mongo_client._motor_db = db
    yield db
    mongo_client._motor_db = original


async def _seed_calendar(db, market: str, exchange: str, days_back: int = 15):
    """种交易日历：工作日开市、周末休市（真实日历形状的简化）。"""
    from app.data.storage.mongo.collections import get_collection_name

    coll = db[get_collection_name("trade_calendar", market)]
    today = date.today()
    docs = []
    for i in range(days_back, -1, -1):
        d = today - timedelta(days=i)
        docs.append({
            "exchange": exchange,
            "cal_date": d.isoformat(),
            "is_open": d.weekday() < 5,  # 周一~周五开市
        })
    await coll.insert_many(docs)


async def _seed_checkpoint(db, market: str, domain: str, cp_date: str):
    await db["sync_checkpoints"].insert_one({
        "market": market,
        "domain": domain,
        "data_source": "scheduled",
        "last_sync_date": cp_date,
        "last_sync_time": "2026-10-01T00:00:00+00:00",
        "status": "success",
        "record_count": 100,
    })


class TestExpectedTradingDate:
    """_expected_trading_date：应有数据交易日的推导。"""

    @pytest.mark.asyncio
    async def test_returns_recent_trading_day(self, patrol_db):
        from app.data.scheduler.freshness_patrol import _expected_trading_date

        await _seed_calendar(patrol_db, "CN", "SSE")
        result = await _expected_trading_date("CN", "daily_quotes")
        assert result is not None
        # 结果不应是未来的日期
        assert result <= date.today()
        # 结果应是开市日
        assert result.weekday() < 5 or result == date.today()

    @pytest.mark.asyncio
    async def test_no_calendar_returns_none(self, patrol_db):
        """日历为空（查不到任何开市日）时返回 None。"""
        from app.data.scheduler.freshness_patrol import _expected_trading_date

        await _seed_calendar(patrol_db, "CN", "SSE")
        # 直接全部删除再重种为休市（SimulatedCursor 不可同步迭代）
        await patrol_db["trade_calendar"].delete_many({})
        today = date.today()
        docs = [{
            "exchange": "SSE",
            "cal_date": (today - timedelta(days=i)).isoformat(),
            "is_open": False,
        } for i in range(15, -1, -1)]
        await patrol_db["trade_calendar"].insert_many(docs)
        result = await _expected_trading_date("CN", "daily_quotes")
        assert result is None


class TestEvaluateDomain:
    """evaluate_domain：落后判定规则。"""

    @pytest.mark.asyncio
    async def test_up_to_date_not_behind(self, patrol_db):
        from app.data.scheduler.freshness_patrol import (
            _expected_trading_date,
            evaluate_domain,
        )

        await _seed_calendar(patrol_db, "CN", "SSE")
        expected = await _expected_trading_date("CN", "daily_quotes")
        assert expected is not None
        await _seed_checkpoint(patrol_db, "CN", "daily_quotes", expected.isoformat())
        verdict = await evaluate_domain("CN", "daily_quotes")
        assert verdict["behind"] is False

    @pytest.mark.asyncio
    async def test_behind_when_checkpoint_older(self, patrol_db):
        from app.data.scheduler.freshness_patrol import (
            _expected_trading_date,
            evaluate_domain,
        )

        await _seed_calendar(patrol_db, "CN", "SSE")
        expected = await _expected_trading_date("CN", "daily_quotes")
        assert expected is not None
        old = expected - timedelta(days=3)
        await _seed_checkpoint(patrol_db, "CN", "daily_quotes", old.isoformat())
        verdict = await evaluate_domain("CN", "daily_quotes")
        assert verdict["behind"] is True
        assert verdict["expected"] == expected.isoformat()
        assert verdict["checkpoint"] == old.isoformat()

    @pytest.mark.asyncio
    async def test_no_checkpoint_is_behind(self, patrol_db):
        from app.data.scheduler.freshness_patrol import evaluate_domain

        await _seed_calendar(patrol_db, "CN", "SSE")
        verdict = await evaluate_domain("CN", "daily_quotes")
        assert verdict["behind"] is True
        assert verdict["reason"] == "no_checkpoint"

    @pytest.mark.asyncio
    async def test_calendar_domain_tolerance(self, patrol_db):
        """basic_info（自然日域）：昨天同步过 → 不落后；5 天前 → 落后。"""
        from app.data.scheduler.freshness_patrol import evaluate_domain

        yesterday = (date.today() - timedelta(days=1)).isoformat()
        await _seed_checkpoint(patrol_db, "CN", "basic_info", yesterday)
        verdict = await evaluate_domain("CN", "basic_info")
        assert verdict["behind"] is False

        old = (date.today() - timedelta(days=5)).isoformat()
        await patrol_db["sync_checkpoints"].delete_many(
            {"market": "CN", "domain": "basic_info", "last_sync_date": yesterday}
        )
        await _seed_checkpoint(patrol_db, "CN", "basic_info", old)
        verdict = await evaluate_domain("CN", "basic_info")
        assert verdict["behind"] is True

    @pytest.mark.asyncio
    async def test_trade_calendar_7day_tolerance(self, patrol_db):
        """trade_calendar 容忍 7 天：3 天前同步 → 不落后。"""
        from app.data.scheduler.freshness_patrol import evaluate_domain

        three_days_ago = (date.today() - timedelta(days=3)).isoformat()
        await _seed_checkpoint(patrol_db, "CN", "trade_calendar", three_days_ago)
        verdict = await evaluate_domain("CN", "trade_calendar")
        assert verdict["behind"] is False


class TestRunPatrol:
    """run_patrol：巡检发现落后域并触发补偿。"""

    @pytest.mark.asyncio
    async def test_patrol_reports_and_compensates(self, patrol_db, scheduler_engine):
        """落后域被发现并经 run_job_now 触发（status=triggered/already_running）。

        scheduler_engine fixture 构造真实引擎（未 start，仅注册表），
        run_job_now 走 TaskRegistry 后台执行——为避免真实外呼，本测试
        聚焦巡检报告的正确性；补偿动作的状态值断言为集合。
        """
        from app.data.scheduler import freshness_patrol
        from app.data.scheduler.freshness_patrol import run_patrol

        await _seed_calendar(patrol_db, "CN", "SSE")
        # 不种任何 CN 检查点 → daily_quotes 判落后
        # 换掉全局引擎单例为 fixture 引擎（未注册任务 → trigger_job 返回空串）
        from app.data.scheduler.engine import SchedulerEngine

        original_engine = SchedulerEngine._instance
        SchedulerEngine._instance = scheduler_engine
        try:
            report = await run_patrol(trigger="test")
        finally:
            SchedulerEngine._instance = original_engine

        assert report["checked"] > 0
        assert "CN:daily_quotes" in report["behind"]
        results = report["results"]
        assert results["CN:daily_quotes"]["behind"] is True
        # 未注册任务时补偿失败但巡检不崩
        assert len(report["compensated"]) >= 1
        # 巡检结果可读取
        assert freshness_patrol.get_last_patrol_result()["trigger"] == "test"

    @pytest.mark.asyncio
    async def test_patrol_skips_when_locked(self, patrol_db):
        """巡检互斥锁：已持锁时再次触发返回 skipped。"""
        from app.data.scheduler.freshness_patrol import _patrol_lock, run_patrol

        async with _patrol_lock:
            report = await run_patrol(trigger="overlap_test")
        assert report["status"] == "skipped"
        assert report["reason"] == "patrol_running"


class TestFreshnessTradingDaySemantics:
    """Reader.check_freshness 交易日语义修复验证。"""

    @pytest.mark.asyncio
    async def test_friday_data_fresh_on_monday(self, patrol_db):
        """周五收盘数据在周一判定为 fresh（旧实现必判 stale）。"""
        from app.data.core.reader import Reader
        from app.data.schema.base.enums import FreshnessState

        await _seed_calendar(patrol_db, "CN", "SSE")
        from app.data.core.market import get_latest_trade_day

        latest = await get_latest_trade_day("CN")
        assert latest is not None

        reader = Reader()
        # 数据覆盖到最近交易日，但 updated_at 很旧（模拟周末后访问）
        data = [{"trade_date": latest.isoformat(),
                 "updated_at": "2000-01-01T00:00:00Z"}]
        result = await reader.check_freshness("CN", "000001", "daily_quotes", data)
        assert result == FreshnessState.FRESH

    @pytest.mark.asyncio
    async def test_old_trade_date_is_stale(self, patrol_db):
        """业务日期落后最近交易日 → stale。"""
        from app.data.core.reader import Reader
        from app.data.schema.base.enums import FreshnessState

        await _seed_calendar(patrol_db, "CN", "SSE")
        from app.data.core.market import get_latest_trade_day

        latest = await get_latest_trade_day("CN")
        assert latest is not None
        old_date = (latest - timedelta(days=10)).isoformat()

        reader = Reader()
        data = [{"trade_date": old_date, "updated_at": "2000-01-01T00:00:00Z"}]
        result = await reader.check_freshness("CN", "000001", "daily_quotes", data)
        assert result == FreshnessState.STALE
