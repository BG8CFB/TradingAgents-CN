"""QMT tick 采集（M2 / PRD FR-06）测试。

覆盖三层：
- reader/provider：144B tick 解析、竞价行锚定时间基、**无竞价行整文件拒读**、
  `trade_date` 与 `ts_code` 注入；
- adapter：`time_ms` 为**当日毫秒**（非 epoch）、5 档数组规整为 Python list、
  `volume` 按 O-2 占位系数直存、可经 Normalizer/Validator 入库；
- worker 流式采集：逐票读→标准化→入库、日写入量阈值**暂停**、覆盖率自检、
  `sync_events` 审计（含 coverage/契约数与超限事件）。

合成 datadir 不依赖真实 QMT 客户端（项目规约：真实代码路径 + 合成文件）。
"""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.data.sources.cn.qmt.adapter import QmtAdapter
from app.data.sources.cn.qmt.field_maps import (
    TICK_VOLUME_TO_SHARE,
    ms_to_time_of_day_ms,
)
from app.data.sources.cn.qmt.provider import QmtProvider
from tests.data.test_qmt_datadir_reader import _recent_records, _write_kline_file

_TODAY = date.today()
_D0 = _TODAY.isoformat()
_D0_YMD = _TODAY.strftime("%Y%m%d")

TZ = timezone(timedelta(hours=8))
# 竞价行锚点：北京时间 09:15:00.000（reader 用首条竞价行校准时间基）
_AUCTION_MS = int(datetime(2026, 10, 20, 9, 15, tzinfo=TZ).timestamp() * 1000)
_AUCTION_TOD_MS = 9 * 3600 * 1000 + 15 * 60 * 1000   # 当日毫秒 33300000

# 首条为集合竞价行（open_interest=12），锚定 09:15:00.000；后续逐秒递增
_TICKS = [
    # (秒偏移, 最新价, 成交额元, 量, 相位, 昨收, 成交笔数, ohlc)
    (0, 10.00, 0, 0, 12, 9.8, 0, (10.0, 10.0, 10.0)),
    (1, 10.10, 101_000, 1000, 0, 9.8, 3, (10.0, 10.2, 9.95)),
    (2, 10.20, 204_000, 2000, 0, 9.8, 7, (10.0, 10.3, 9.95)),
]


def _pack_tick(
    raw_ts: int, last: float, amount: int, vol: int, phase: int,
    last_close: float, tx_num: int, ohlc: tuple,
    ask_p=(10.21, 10.22, 0.0, 0.0, 0.0), ask_v=(10, 20, 0, 0, 0),
    bid_p=(10.20, 10.19, 0.0, 0.0, 0.0), bid_v=(30, 40, 0, 0, 0),
) -> bytes:
    """合成一条 144B tick 记录（布局见 reader._TICK_DTYPE）。

    注意 ``amount`` 是 **u64**（占 2 个 u32 槽位），必须用 Q 而非 I ——
    reader 审计 D15：日成交额 > 2^32 时 u32 会静默回绕。
    """
    import struct

    o, h, low = ohlc
    return struct.pack(
        "<IIIIQIIIIIIIIII" + "I" * 20,
        raw_ts, 0, int(last * 1000), 0,
        int(amount),
        int(vol), int(phase), 0, int(tx_num), 0,
        int(o * 1000), int(h * 1000), int(low * 1000), 0,
        int(last_close * 1000),
        *[int(p * 1000) for p in ask_p], *ask_v,
        *[int(p * 1000) for p in bid_p], *bid_v,
    )


def _tick_bytes(records=None) -> bytes:
    recs = records if records is not None else _TICKS
    return b"".join(
        _pack_tick(sec * 1000, last, amt, vol, phase, lc, tx, ohlc)
        for (sec, last, amt, vol, phase, lc, tx, ohlc) in recs
    )


def _write_tick_file(root: Path, market: str, code: str, ymd: str,
                     records=None) -> Path:
    path = root / market / "0" / code / f"{ymd}.dat"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_tick_bytes(records))
    return path


def _mk_tree(tmp_path: Path, *, with_tick_for=("SZ/000001", "SH/600000")) -> Path:
    """指数日线（日历）+ 两只股票日线（进宇宙）+ 指定的 tick 文件。"""
    daily = _recent_records([2, 1, 0])
    _write_kline_file(tmp_path / "SH" / "86400" / "000001.DAT", daily)   # 上证指数
    _write_kline_file(tmp_path / "SZ" / "86400" / "000001.DAT", daily)
    _write_kline_file(tmp_path / "SH" / "86400" / "600000.DAT", daily)
    for item in with_tick_for:
        market, code = item.split("/")
        _write_tick_file(tmp_path, market, code, _D0_YMD)
    return tmp_path


def _enable(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "app.data.sources.cn.qmt.provider.get_qmt_datadir", lambda: str(tmp_path)
    )
    from app.core.config import settings

    monkeypatch.setattr(settings, "QMT_ENABLED", True)


@pytest.fixture
def provider(tmp_path, monkeypatch) -> QmtProvider:
    _mk_tree(tmp_path)
    _enable(monkeypatch, tmp_path)
    return QmtProvider()


def _raw_frame() -> "object":
    """与 provider 注入后同形的 tick 原始帧（adapter 单测用，固定日期便于断言）。"""
    import pandas as pd

    rows = []
    for (sec, last, amt, vol, phase, lc, tx, ohlc) in _TICKS:
        rows.append({
            "ts_code": "000001.SZ",
            "trade_date": _D0,
            "time": _AUCTION_MS + sec * 1000,
            "lastPrice": last,
            "amount": float(amt),
            "volume": vol,
            "lastClose": lc,
            "market_phase_status": phase,
            "askPrice": [10.21, 10.22, 0.0, 0.0, 0.0],
            "askVol": [10, 20, 0, 0, 0],
            "bidPrice": [10.20, 10.19, 0.0, 0.0, 0.0],
            "bidVol": [30, 40, 0, 0, 0],
            "open": ohlc[0], "high": ohlc[1], "low": ohlc[2],
            "transactionNum": tx,
        })
    return pd.DataFrame(rows)


class TestTimeOfDay:
    def test_ms_to_time_of_day(self):
        assert ms_to_time_of_day_ms(_AUCTION_MS) == _AUCTION_TOD_MS
        # 14:59:59
        end = _AUCTION_MS + (5 * 3600 + 44 * 60 + 59) * 1000
        assert ms_to_time_of_day_ms(end) == (14 * 3600 + 59 * 60 + 59) * 1000


class TestProviderTick:
    async def test_single_symbol_single_day(self, provider: QmtProvider):
        df = await provider.get_tick_quotes("000001", _D0, _D0)
        assert not df.empty
        assert set(df["ts_code"]) == {"000001.SZ"}
        assert set(df["trade_date"]) == {_D0}
        assert len(df) == len(_TICKS)
        # 竞价行被锚定为 09:15:00（北京时间）
        assert df["time"].iloc[0] == _AUCTION_MS

    async def test_read_tick_one_annotates_context(self, provider: QmtProvider):
        df = await provider.read_tick_one("600000.SH", _D0_YMD)
        assert list(df.columns[:1]) == ["ts_code"]
        assert "trade_date" in df.columns
        assert df["trade_date"].iloc[0] == _D0

    async def test_missing_file_returns_empty(self, provider: QmtProvider):
        df = await provider.get_tick_quotes("600000", "2020-01-02", "2020-01-02")
        assert df.empty

    async def test_no_auction_row_is_rejected(self, tmp_path, monkeypatch):
        """无竞价行 → 时间基不可校准 → 整文件拒读（绝不返回相对时刻）。"""
        no_auction = [r for r in _TICKS if r[4] != 12]
        _mk_tree(tmp_path, with_tick_for=())
        _write_tick_file(tmp_path, "SZ", "000001", _D0_YMD, records=no_auction)
        _enable(monkeypatch, tmp_path)

        p = QmtProvider()
        df = await p.get_tick_quotes("000001", _D0, _D0)
        assert df.empty


class TestAdapterTick:
    def test_fields_units_and_arrays(self):
        rows = QmtAdapter().adapt_tick_quotes(_raw_frame())
        assert len(rows) == len(_TICKS)

        first = rows[0]
        assert first.symbol == "000001"
        assert first.market == "CN"
        assert first.data_source == "qmt"
        assert first.trade_date == _D0
        # time_ms 是当日毫秒（09:15:00 = 33300000），不是 epoch
        assert first.time_ms == _AUCTION_TOD_MS
        assert first.datetime == "2026-10-20 09:15:00"
        assert first.last_price == pytest.approx(10.0)
        assert first.last_close == pytest.approx(9.8)
        assert first.market_phase_status == 12
        # 5 档规整为 Python list（BSON 可序列化）
        assert first.ask_price == [10.21, 10.22, 0.0, 0.0, 0.0]
        assert all(isinstance(v, float) for v in first.ask_price)
        assert first.ask_vol == [10, 20, 0, 0, 0]
        assert all(isinstance(v, int) for v in first.ask_vol)
        assert first.bid_vol == [30, 40, 0, 0, 0]

        second = rows[1]
        assert second.transaction_num == 3
        assert second.time_ms == 9 * 3600 * 1000 + 15 * 60 * 1000 + 1000
        # volume 按 O-2 占位系数（当前 1.0 = 原样落库）
        assert second.volume == pytest.approx(1000 * TICK_VOLUME_TO_SHARE)

    def test_to_db_doc_has_arrays_and_no_dialect(self):
        doc = QmtAdapter().adapt_tick_quotes(_raw_frame())[1].to_db_doc()
        assert doc["trade_date"] == _D0
        assert doc["time_ms"] == (9 * 3600 + 15 * 60 + 1) * 1000
        assert doc["ask_price"] == [10.21, 10.22, 0.0, 0.0, 0.0]
        for leaked in ("ts_code", "lastPrice", "lastClose", "askPrice", "time", "openInt"):
            assert leaked not in doc

    def test_empty_input(self):
        import pandas as pd

        assert QmtAdapter().adapt_tick_quotes(pd.DataFrame()) == []


class TestPlatformWiring:
    def test_normalizer_and_validator_accept_tick(self):
        from app.data.processor.normalizer import NORMALIZE_OK, Normalizer
        from app.data.processor.validator import Validator

        result = Normalizer().normalize_with_status(
            _raw_frame(), "tick_quotes", QmtAdapter()
        )
        assert result.status == NORMALIZE_OK
        valid, errors = Validator().validate(result.records, "tick_quotes", "CN")
        assert not errors
        assert len(valid) == len(_TICKS)


class TestCollectTick:
    @pytest.mark.asyncio
    async def test_streams_into_tick_collection(self, tmp_path, inject_sim_db, monkeypatch):
        """逐票流式采集 → 写入 stock_tick_quotes，并落覆盖率审计事件。"""
        from app.data.storage.mongo.collections import get_collection_name
        from tests.data.test_qmt_e2e_chain import _install_bulk_write
        from app.worker.qmt.tick_collect import collect_tick

        _mk_tree(tmp_path)
        _enable(monkeypatch, tmp_path)
        coll = _install_bulk_write(
            inject_sim_db, get_collection_name("tick_quotes", "CN")
        )

        summary = await collect_tick(_D0, daily_limit=10_000_000)

        assert summary["success"] is True
        assert summary["contracts_total"] == 2
        assert summary["contracts_with_data"] == 2
        assert summary["coverage_ratio"] == 1.0
        assert summary["written_rows"] == len(_TICKS) * 2
        assert summary["paused_by_limit"] is False

        docs = await coll.find({"symbol": "000001"}).to_list(length=10)
        assert len(docs) == len(_TICKS)
        for d in docs:
            assert d["data_source"] == "qmt"
            assert d["trade_date"] == _D0
            assert isinstance(d["time_ms"], int)
            assert isinstance(d["ask_price"], list)
        # 两只有数据的标的各自独立入库
        assert len(await coll.find({"symbol": "600000"}).to_list(length=10)) == len(_TICKS)

        events = await inject_sim_db["sync_events"].find(
            {"data_source": "qmt_tick_collect"}
        ).to_list(length=5)
        assert len(events) == 1
        assert events[0]["event_type"] == "SYNC_SUCCESS"
        assert events[0]["domain"] == "tick_quotes"
        assert events[0]["record_count"] == summary["written_rows"]
        assert events[0]["coverage_ratio"] == 1.0
        assert events[0]["contracts_with_data"] == 2

    @pytest.mark.asyncio
    async def test_pauses_at_daily_limit_and_alerts(
        self, tmp_path, inject_sim_db, monkeypatch
    ):
        """超阈值 → 暂停并双事件告警，但**不抛异常**（其余域不受影响）。"""
        from app.data.storage.mongo.collections import get_collection_name
        from tests.data.test_qmt_e2e_chain import _install_bulk_write
        from app.worker.qmt.tick_collect import collect_tick

        _mk_tree(tmp_path)
        _enable(monkeypatch, tmp_path)
        _install_bulk_write(
            inject_sim_db, get_collection_name("tick_quotes", "CN")
        )

        summary = await collect_tick(_D0, daily_limit=1)

        assert summary["paused_by_limit"] is True
        assert summary["success"] is False
        assert summary["written_rows"] >= 1

        events = await inject_sim_db["sync_events"].find({}).to_list(length=10)
        kinds = {e["data_source"] for e in events}
        assert "qmt_tick_collect" in kinds
        assert "qmt_tick_limit_pause" in kinds
        pause = [e for e in events if e["data_source"] == "qmt_tick_limit_pause"][0]
        assert pause["threshold"] == 1
        assert pause["resumed"] is False
        assert pause["event_type"] == "SYNC_FAILED"

    @pytest.mark.asyncio
    async def test_coverage_gap_is_audited(self, tmp_path, inject_sim_db, monkeypatch):
        """部分标的无 tick 数据 → 覆盖率不足仍算采集成功，但审计里可见。"""
        from app.data.storage.mongo.collections import get_collection_name
        from tests.data.test_qmt_e2e_chain import _install_bulk_write
        from app.worker.qmt.tick_collect import collect_tick

        _mk_tree(tmp_path, with_tick_for=("SZ/000001",))   # 600000 无 tick
        _enable(monkeypatch, tmp_path)
        _install_bulk_write(
            inject_sim_db, get_collection_name("tick_quotes", "CN")
        )

        summary = await collect_tick(_D0, daily_limit=10_000_000)
        assert summary["success"] is True
        assert summary["contracts_total"] == 2
        assert summary["contracts_with_data"] == 1
        assert summary["coverage_ratio"] == pytest.approx(0.5)

        events = await inject_sim_db["sync_events"].find(
            {"data_source": "qmt_tick_collect"}
        ).to_list(length=5)
        assert events[0]["coverage_ratio"] == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_disabled_source_skips(self, tmp_path, inject_sim_db, monkeypatch):
        from app.core.config import settings
        from app.worker.qmt.tick_collect import collect_tick

        _mk_tree(tmp_path)
        monkeypatch.setattr(
            "app.data.sources.cn.qmt.provider.get_qmt_datadir", lambda: str(tmp_path)
        )
        monkeypatch.setattr(settings, "QMT_ENABLED", False)

        summary = await collect_tick(_D0)
        assert summary["success"] is False
        assert summary.get("reason") == "QMT_ENABLED=false"
        assert summary["written_rows"] == 0
