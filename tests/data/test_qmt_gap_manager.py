"""增量缺口管理（M2 / PRD FR-12）测试。

覆盖：
- `DataGapRepo` 生命周期（登记幂等、轮次累加、达上限转 abandoned、运维重置）；
- 检测口径：以**库内交易日历**为基准，逐日检查分区存在性（分时用 datetime 区间）；
- `run_gap_fill`：已补齐的缺口直接消除登记；补采失败按轮次累积并告警；
- 审计：缺口生命周期写 `sync_events`（data_source="qmt_gap"）。

测试不触碰网络：失败路径统一用 tick 域（无既有源兜底），避免走到 tushare/akshare。
"""

from datetime import datetime, timedelta

_DAYS = [
    (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d"),
    (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
]
_D0 = _DAYS[-1]


async def _put_calendar(db, dates):
    """写入交易日历（SSE，全部开市）。"""
    from app.data.storage.mongo.client import get_motor_db
    from app.data.storage.mongo.collections import get_collection_name

    coll = get_motor_db()[get_collection_name("trade_calendar", "CN")]
    for d in dates:
        await coll.insert_one({
            "exchange": "SSE", "cal_date": d, "is_open": True,
            "pretrade_date": None, "symbol": "__calendar__",
            "market": "CN", "data_source": "tushare",
        })


async def _put_rows(db, domain, day, market="CN"):
    from app.data.storage.mongo.client import get_motor_db
    from app.data.storage.mongo.collections import get_collection_name

    coll = get_motor_db()[get_collection_name(domain, market)]
    if domain == "intraday_quotes":
        await coll.insert_one({"symbol": "000001", "datetime": f"{day} 09:35:00",
                               "freq": "5min", "market": "CN"})
    else:
        await coll.insert_one({"symbol": "000001", "trade_date": day,
                               "market": "CN"})


class TestDataGapRepo:
    async def test_register_is_idempotent(self, inject_sim_db):
        from app.data.storage.mongo.repositories.data_gap_repo import DataGapRepo

        repo = DataGapRepo()
        assert await repo.register("CN", "daily_quotes", _D0, "partition_missing") is True
        # 二次登记不重置状态与轮次
        assert await repo.register("CN", "daily_quotes", _D0, "partition_missing") is False

        gaps = await repo.open_gaps("CN")
        assert len(gaps) == 1
        assert gaps[0]["attempts"] == 0
        assert gaps[0]["status"] == "open"
        assert gaps[0]["first_seen_at"]

    async def test_open_gaps_sorted_and_filtered(self, inject_sim_db):
        from app.data.storage.mongo.repositories.data_gap_repo import DataGapRepo

        repo = DataGapRepo()
        await repo.register("CN", "daily_quotes", _DAYS[1])
        await repo.register("CN", "daily_quotes", _DAYS[0])
        await repo.register("CN", "tick_quotes", _DAYS[0])

        daily = await repo.open_gaps("CN", domain="daily_quotes")
        assert [g["gap_date"] for g in daily] == sorted(_DAYS)
        assert len(await repo.open_gaps("CN")) == 3

    async def test_fill_clears_gap(self, inject_sim_db):
        from app.data.storage.mongo.repositories.data_gap_repo import DataGapRepo

        repo = DataGapRepo()
        await repo.register("CN", "daily_quotes", _D0)
        await repo.mark_filled("CN", "daily_quotes", _D0, "qmt")

        assert await repo.open_gaps("CN") == []
        doc = await inject_sim_db["data_gaps"].find_one({"gap_date": _D0})
        assert doc["status"] == "filled"
        assert doc["filled_by"] == "qmt"

    async def test_attempt_bumps_until_abandoned(self, inject_sim_db):
        from app.data.storage.mongo.repositories.data_gap_repo import DataGapRepo

        repo = DataGapRepo()
        await repo.register("CN", "tick_quotes", _D0)

        first = await repo.bump_attempt("CN", "tick_quotes", _D0, "empty", 3)
        assert first == {"attempts": 1, "status": "open", "abandoned": False}
        second = await repo.bump_attempt("CN", "tick_quotes", _D0, "empty", 3)
        assert second["attempts"] == 2
        third = await repo.bump_attempt("CN", "tick_quotes", _D0, "empty", 3)
        assert third == {"attempts": 3, "status": "abandoned", "abandoned": True}
        # abandoned 后不再出现在待补列表（防死循环）
        assert await repo.open_gaps("CN") == []

    async def test_reset_reopens_abandoned(self, inject_sim_db):
        from app.data.storage.mongo.repositories.data_gap_repo import DataGapRepo

        repo = DataGapRepo()
        await repo.register("CN", "tick_quotes", _D0)
        await repo.bump_attempt("CN", "tick_quotes", _D0, "empty", 1)
        assert await repo.open_gaps("CN") == []

        await repo.reset("CN", "tick_quotes", _D0)
        gaps = await repo.open_gaps("CN")
        assert len(gaps) == 1
        assert gaps[0]["attempts"] == 0


class TestDetection:
    async def test_expected_dates_come_from_platform_calendar(self, inject_sim_db):
        from app.worker.qmt.gap_manager import expected_trade_dates

        await _put_calendar(inject_sim_db, _DAYS)
        dates = await expected_trade_dates(10)
        assert dates == sorted(_DAYS)
        # 只回看最近 N 个
        assert await expected_trade_dates(1) == [_DAYS[1]]

    async def test_empty_calendar_disables_detection(self, inject_sim_db):
        """无日历基准时不做判定（否则每个日期都会被误判成缺口）。"""
        from app.worker.qmt.gap_manager import detect_and_register

        result = await detect_and_register(lookback_days=10)
        assert result["dates"] == []
        assert result["registered"] == {}

    async def test_partition_presence_per_domain(self, inject_sim_db):
        from app.worker.qmt.gap_manager import has_partition

        await _put_rows(inject_sim_db, "daily_quotes", _D0)
        await _put_rows(inject_sim_db, "tick_quotes", _D0)
        await _put_rows(inject_sim_db, "intraday_quotes", _D0)

        assert await has_partition("CN", "daily_quotes", _D0) is True
        assert await has_partition("CN", "tick_quotes", _D0) is True
        # 分时的日期字段是 datetime，需区间匹配
        assert await has_partition("CN", "intraday_quotes", _D0) is True
        assert await has_partition("CN", "intraday_quotes", _DAYS[0]) is False
        assert await has_partition("CN", "daily_quotes", _DAYS[0]) is False

    async def test_detect_registers_only_missing_domains(self, inject_sim_db):
        from app.worker.qmt.gap_manager import detect_and_register

        await _put_calendar(inject_sim_db, _DAYS)
        for d in _DAYS:
            await _put_rows(inject_sim_db, "daily_quotes", d)

        result = await detect_and_register(lookback_days=10)
        assert "daily_quotes" not in result["registered"]
        assert set(result["registered"]) == {"intraday_quotes", "tick_quotes"}
        assert result["registered"]["tick_quotes"] == sorted(_DAYS)

    async def test_detect_is_idempotent_across_runs(self, inject_sim_db):
        from app.worker.qmt.gap_manager import detect_and_register

        await _put_calendar(inject_sim_db, [_D0])
        first = await detect_and_register(lookback_days=10)
        assert first["registered"]["tick_quotes"] == [_D0]
        second = await detect_and_register(lookback_days=10)
        assert second["registered"] == {}
        # 三个域都已登记（daily/intraday/tick 均无数据）
        assert second["existing"] == 3


class TestRunGapFill:
    async def test_skip_when_disabled(self, inject_sim_db):
        from app.core.config import settings
        from app.worker.qmt.gap_manager import run_gap_fill

        old = settings.QMT_ENABLED
        settings.QMT_ENABLED = False
        try:
            result = await run_gap_fill()
        finally:
            settings.QMT_ENABLED = old
        assert result["skipped"] is True
        assert result["reason"] == "QMT_ENABLED=false"

    async def test_preexisting_partition_clears_gap(
        self, tmp_path, inject_sim_db, monkeypatch
    ):
        """缺口已被其他路径补齐 → 直接消除登记，不去碰数据源。"""
        from app.core.config import settings
        from app.data.storage.mongo.repositories.data_gap_repo import DataGapRepo
        from app.worker.qmt.gap_manager import run_gap_fill

        await _put_calendar(inject_sim_db, [_D0])
        await _put_rows(inject_sim_db, "daily_quotes", _D0)
        repo = DataGapRepo()
        await repo.register("CN", "daily_quotes", _D0)

        monkeypatch.setattr(
            "app.data.sources.cn.qmt.provider.get_qmt_datadir", lambda: str(tmp_path)
        )
        monkeypatch.setattr(settings, "QMT_ENABLED", True)

        result = await run_gap_fill(domains=["daily_quotes"])
        assert result["success"] is True
        assert result["filled"] == [
            {"domain": "daily_quotes", "gap_date": _D0, "source": "preexisting"}
        ]
        assert await repo.open_gaps("CN") == []

        events = await inject_sim_db["sync_events"].find(
            {"data_source": "qmt_gap"}
        ).to_list(length=10)
        assert any(e["action"] == "filled" for e in events)

    async def test_failure_abandons_after_cap(
        self, tmp_path, inject_sim_db, monkeypatch
    ):
        """tick 域无 datadir 且无既有源兜底 → 达到轮次上限后放弃并告警。"""
        from app.core.config import settings
        from app.worker.qmt.gap_manager import run_gap_fill

        await _put_calendar(inject_sim_db, [_D0])
        monkeypatch.setattr(
            "app.data.sources.cn.qmt.provider.get_qmt_datadir", lambda: str(tmp_path)
        )
        monkeypatch.setattr(settings, "QMT_ENABLED", True)

        result = await run_gap_fill(max_attempts=1, domains=["tick_quotes"])
        assert result["abandoned"], result
        assert result["success"] is False
        assert result["abandoned"][0]["gap_date"] == _D0
        assert result["abandoned"][0]["attempts"] == 1

        docs = await inject_sim_db["data_gaps"].find({}).to_list(length=5)
        assert docs[0]["status"] == "abandoned"
        events = await inject_sim_db["sync_events"].find(
            {"data_source": "qmt_gap"}
        ).to_list(length=10)
        assert any(e["action"] == "fill_failed" for e in events)

    async def test_non_abandoned_failure_stays_open(
        self, tmp_path, inject_sim_db, monkeypatch
    ):
        from app.core.config import settings
        from app.worker.qmt.gap_manager import run_gap_fill

        await _put_calendar(inject_sim_db, [_D0])
        monkeypatch.setattr(
            "app.data.sources.cn.qmt.provider.get_qmt_datadir", lambda: str(tmp_path)
        )
        monkeypatch.setattr(settings, "QMT_ENABLED", True)

        result = await run_gap_fill(max_attempts=3, domains=["tick_quotes"])
        assert result["still_open"] == 1
        assert result["abandoned"] == []
        docs = await inject_sim_db["data_gaps"].find({}).to_list(length=5)
        assert docs[0]["status"] == "open"
        assert docs[0]["attempts"] == 1
