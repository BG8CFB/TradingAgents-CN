"""QMT 分时采集（M2 / PRD FR-04）测试。

覆盖：
- freq 词表映射（平台 '1min'/'5min' ↔ datadir 周期 '1m'/'5m'），非法频率必须
  报错而非静默降级（QMT datadir 只有这两个周期目录）；
- Provider 单票/全市场批量分时读取（合成 datadir，64B 记录与日线同构）；
- Adapter 单位换算（手→股 ×100）、amount 直存元、datetime 派生、pct_chg 现算；
- Normalizer 路由到 adapt_intraday_quotes 并可入库（唯一键 symbol+datetime+freq）；
- worker 侧 `_REPO_TABLE` 必须注册 intraday_quotes（曾缺失 → sync() 直接 ValueError）；
- 能力矩阵/优先级：qmt 在 intraday_quotes 链末位，开关关闭时整链为空。
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.data.sources.cn.qmt.adapter import QmtAdapter
from app.data.sources.cn.qmt.field_maps import (
    FREQ_TO_READER_PERIOD,
    freq_to_reader_period,
    reader_period_to_freq,
)
from app.data.sources.cn.qmt.provider import QmtProvider
from tests.data.test_qmt_datadir_reader import (
    _pack_kline,
    _recent_records,
    _write_kline_file,
)

TZ = timezone(timedelta(hours=8))

_D1 = (date.today() - timedelta(days=1)).isoformat()

# 分时合成记录的 (open, high, low, close, volume手, amount元) 三条 5m bar
_BARS = [
    (10.0, 10.4, 9.9, 10.2, 120, 122_400),
    (10.2, 10.6, 10.1, 10.5, 80, 84_000),
    (10.5, 10.8, 10.4, 10.6, 60, 63_600),
]


def _minute_records(day: date, *, freq_min: int = 5, pre_close: float = 9.8) -> list[bytes]:
    """合成当日连续分钟 bar（ts 严格递增，status 文件级全等）。"""
    start = datetime(day.year, day.month, day.day, 9, 35, tzinfo=TZ)
    out = []
    for i, (o, h, low, c, vol, amt) in enumerate(_BARS):
        ts = int((start + timedelta(minutes=freq_min * i)).timestamp())
        out.append(_pack_kline(ts, o, h, low, c, vol, amt, pre_close))
    return out


def _mk_tree(tmp_path):
    """含指数（日历）+ 两只股票 + 两只股票 5m/1m 分时文件的就绪 datadir。"""
    daily = _recent_records([2, 1, 0])
    _write_kline_file(tmp_path / "SH" / "86400" / "000001.DAT", daily)   # 上证指数 → 日历
    _write_kline_file(tmp_path / "SZ" / "86400" / "000001.DAT", daily)
    _write_kline_file(tmp_path / "SH" / "86400" / "600000.DAT", daily)

    day = date.today() - timedelta(days=1)
    for market, code in (("SZ", "000001"), ("SH", "600000")):
        _write_kline_file(
            tmp_path / market / "300" / f"{code}.DAT",
            _minute_records(day, freq_min=5),
        )
        _write_kline_file(
            tmp_path / market / "60" / f"{code}.DAT",
            _minute_records(day, freq_min=1),
        )
    return tmp_path


@pytest.fixture
def provider(tmp_path, monkeypatch) -> QmtProvider:
    _mk_tree(tmp_path)
    monkeypatch.setattr(
        "app.data.sources.cn.qmt.provider.get_qmt_datadir", lambda: str(tmp_path)
    )
    from app.core.config import settings

    monkeypatch.setattr(settings, "QMT_ENABLED", True)
    return QmtProvider()


@pytest.fixture
def adapter() -> QmtAdapter:
    return QmtAdapter()


# ---------------------------------------------------------------------------
# freq 词表
# ---------------------------------------------------------------------------


class TestFreqMapping:
    def test_supported_pairs(self):
        assert FREQ_TO_READER_PERIOD == {"1min": "1m", "5min": "5m"}
        assert freq_to_reader_period("5min") == "5m"
        assert freq_to_reader_period("1MIN") == "1m"      # 大小写/空格宽容
        assert freq_to_reader_period("  5min ") == "5m"
        assert reader_period_to_freq("5m") == "5min"
        assert reader_period_to_freq("1m") == "1min"

    def test_unsupported_freq_raises(self):
        """15/30/60min 在 datadir 无对应目录，必须显式报错而非静默降级。"""
        with pytest.raises(ValueError, match="不支持 freq"):
            freq_to_reader_period("30min")
        with pytest.raises(ValueError):
            freq_to_reader_period("")
        assert reader_period_to_freq("5m") == "5min"
        with pytest.raises(ValueError):
            reader_period_to_freq("30m")


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class TestProviderIntraday:
    async def test_single_symbol_returns_annotated_frame(self, provider: QmtProvider):
        df = await provider.get_intraday_quotes("000001", _D1, _D1, freq="5min")
        assert not df.empty
        assert df.columns[0] == "ts_code"
        assert "freq" in df.columns
        assert set(df["ts_code"]) == {"000001.SZ"}
        assert set(df["freq"]) == {"5min"}
        assert len(df) == len(_BARS)
        # 手为原始单位（换算在 Adapter 层，DD-05 单一职责）
        assert list(df["volume"]) == [b[4] for b in _BARS]
        # time 为 bar 时刻（ms epoch），北京时区 09:35 起
        first = datetime.fromtimestamp(int(df["time"].iloc[0]) / 1000, TZ)
        assert (first.hour, first.minute) == (9, 35)

    async def test_1min_and_5min_are_distinct(self, provider: QmtProvider):
        m5 = await provider.get_intraday_quotes("600000", _D1, _D1, freq="5min")
        m1 = await provider.get_intraday_quotes("600000", _D1, _D1, freq="1min")
        assert set(m5["freq"]) == {"5min"}
        assert set(m1["freq"]) == {"1min"}
        assert len(m5) == len(_BARS) == len(m1)

    async def test_unsupported_freq_raises_value_error(self, provider: QmtProvider):
        with pytest.raises(ValueError, match="不支持 freq"):
            await provider.get_intraday_quotes("000001", _D1, _D1, freq="30min")

    async def test_batch_range_covers_universe(self, provider: QmtProvider):
        df = await provider.get_intraday_quotes_batch_range(_D1, _D1, freq="5min")
        assert not df.empty
        assert set(df["ts_code"]) == {"000001.SZ", "600000.SH"}
        assert len(df) == len(_BARS) * 2
        assert set(df["freq"]) == {"5min"}

    async def test_batch_range_skips_symbol_without_minute_file(
        self, tmp_path, monkeypatch
    ):
        """无分时文件的标的跳过而非中断整批（缺口由补采承接）。"""
        _mk_tree(tmp_path)
        # 600000 只有日线、无 5m 文件
        (tmp_path / "SH" / "300" / "600000.DAT").unlink()
        monkeypatch.setattr(
            "app.data.sources.cn.qmt.provider.get_qmt_datadir", lambda: str(tmp_path)
        )
        from app.core.config import settings

        monkeypatch.setattr(settings, "QMT_ENABLED", True)
        p = QmtProvider()
        df = await p.get_intraday_quotes_batch_range(_D1, _D1, freq="5min")
        assert set(df["ts_code"]) == {"000001.SZ"}

    async def test_disabled_source_raises_unavailable(self, tmp_path, monkeypatch):
        _mk_tree(tmp_path)
        monkeypatch.setattr(
            "app.data.sources.cn.qmt.provider.get_qmt_datadir", lambda: str(tmp_path)
        )
        from app.core.config import settings
        from app.data.sources.base.exceptions import DataSourceUnavailableError

        monkeypatch.setattr(settings, "QMT_ENABLED", False)
        p = QmtProvider()
        with pytest.raises(DataSourceUnavailableError):
            await p.get_intraday_quotes("000001", _D1, _D1, freq="5min")


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class TestAdapterIntraday:
    async def test_schema_fields(self, provider: QmtProvider, adapter: QmtAdapter):
        raw = await provider.get_intraday_quotes("000001", _D1, _D1, freq="5min")
        rows = adapter.adapt_intraday_quotes(raw)
        assert len(rows) == len(_BARS)

        first = rows[0]
        assert first.symbol == "000001"
        assert first.market == "CN"
        assert first.data_source == "qmt"
        assert first.freq == "5min"
        # datetime：'YYYY-MM-DD HH:MM:SS'，当日 09:35
        assert first.datetime == f"{_D1} 09:35:00"
        # volume 手→股 ×100
        assert first.volume == pytest.approx(120 * 100.0)
        assert first.open == pytest.approx(10.0)
        assert first.close == pytest.approx(10.2)
        # amount 直存元（不 ×1000）
        assert first.amount == pytest.approx(122_400.0)
        # pct_chg 按最新价 vs 昨收现算
        assert first.pct_chg == pytest.approx(round((10.2 - 9.8) / 9.8 * 100, 4))

    async def test_to_db_doc_round_trip(self, provider: QmtProvider, adapter: QmtAdapter):
        raw = await provider.get_intraday_quotes("600000", _D1, _D1, freq="1min")
        doc = adapter.adapt_intraday_quotes(raw)[0].to_db_doc()
        assert doc["symbol"] == "600000"
        assert doc["freq"] == "1min"
        assert doc["volume"] == pytest.approx(120 * 100.0)
        assert "updated_at" in doc
        # 无 datadir 方言列泄漏（D-5）
        for leaked in ("ts_code", "preClose", "time", "suspendFlag", "adj_f_cum"):
            assert leaked not in doc

    def test_empty_input(self, adapter: QmtAdapter):
        assert adapter.adapt_intraday_quotes([]) == []
        import pandas as pd

        assert adapter.adapt_intraday_quotes(pd.DataFrame()) == []


# ---------------------------------------------------------------------------
# 平台链路
# ---------------------------------------------------------------------------


class TestPlatformWiring:
    def test_normalizer_routes_intraday_to_adapter(self):
        from app.data.processor.normalizer import NORMALIZE_OK, Normalizer

        raw = [
            {
                "ts_code": "000001.SZ", "freq": "5min", "time": 0,
                "open": 10.0, "high": 10.1, "low": 9.9, "close": 10.0,
                "volume": 100, "amount": 100_000.0, "preClose": 9.9,
            }
        ]
        result = Normalizer().normalize_with_status(
            raw, "intraday_quotes", QmtAdapter()
        )
        assert result.status == NORMALIZE_OK
        assert result.records[0]["freq"] == "5min"
        assert result.records[0]["volume"] == pytest.approx(10_000.0)

    def test_repo_table_registers_intraday_quotes(self):
        """曾缺失 → QmtIntradayQuotesSync.sync() 会直接 ValueError。"""
        from app.worker.base_market_sync import _get_repo, _REPO_TABLE

        assert "intraday_quotes" in _REPO_TABLE
        assert hasattr(_get_repo("intraday_quotes"), "upsert_many")

    def test_qmt_is_last_in_intraday_chain(self):
        from app.core.config import settings
        from app.data.core.registry.capability import CapabilityRegistry

        old = settings.QMT_ENABLED
        settings.QMT_ENABLED = True
        try:
            chain = CapabilityRegistry().get_ordered_sources("CN", "intraday_quotes")
        finally:
            settings.QMT_ENABLED = old
        assert chain[-1] == "qmt"
        assert "tushare" in chain

    def test_disabled_removes_qmt_from_intraday_chain(self):
        from app.core.config import settings
        from app.data.core.registry.capability import CapabilityRegistry

        old = settings.QMT_ENABLED
        settings.QMT_ENABLED = False
        try:
            chain = CapabilityRegistry().get_ordered_sources("CN", "intraday_quotes")
        finally:
            settings.QMT_ENABLED = old
        assert "qmt" not in chain


class TestWorkerFreqParsing:
    def test_parse_dedupes_and_skips_unknown(self):
        from app.worker.qmt.jobs import _parse_intraday_freqs

        assert _parse_intraday_freqs("5min") == ["5min"]
        assert _parse_intraday_freqs("5min,1min") == ["5min", "1min"]
        assert _parse_intraday_freqs(" 5min , 5min ,1MIN ") == ["5min", "1min"]
        # 未知频率只跳过（不抛异常，其余频率仍应采集）
        assert _parse_intraday_freqs("30min,5min") == ["5min"]
        assert _parse_intraday_freqs("") == []
        assert _parse_intraday_freqs(None) == []


@pytest.mark.asyncio
async def test_pinned_sync_writes_intraday_collection(
    tmp_path, inject_sim_db, monkeypatch,
):
    """钉死单源的域同步 → 入库既有 stock_intraday_quotes（同集合同 Schema）。

    同时回归 `_REPO_TABLE` 缺少 intraday_quotes 的缺陷：缺条目时 sync() 会在
    取 Repo 阶段抛 ValueError（单域失败），而非写入数据。
    """
    from app.data.storage.mongo.collections import get_collection_name
    from tests.data.test_qmt_e2e_chain import _install_bulk_write

    _mk_tree(tmp_path)
    monkeypatch.setattr(
        "app.data.sources.cn.qmt.provider.get_qmt_datadir", lambda: str(tmp_path)
    )
    from app.core.config import settings

    monkeypatch.setattr(settings, "QMT_ENABLED", True)

    coll = _install_bulk_write(
        inject_sim_db, get_collection_name("intraday_quotes", "CN")
    )

    from app.worker.qmt.jobs import QmtIntradayQuotesSync

    result = await QmtIntradayQuotesSync().sync(
        "get_intraday_quotes_batch_range",
        lambda: {"start_date": _D1, "end_date": _D1, "freq": "5min"},
    )
    assert result["success"] is True, result
    assert result["domain"] == "intraday_quotes"

    docs = await coll.find({"symbol": "000001"}).to_list(length=10)
    assert len(docs) == len(_BARS)
    expected_volumes = sorted(b[4] * 100.0 for b in _BARS)  # 手 → 股
    assert sorted(d["volume"] for d in docs) == pytest.approx(expected_volumes)
    for d in docs:
        assert d["data_source"] == "qmt"
        assert d["freq"] == "5min"
        assert d["datetime"].startswith(_D1)
        assert "ts_code" not in d and "preClose" not in d

    # 分时与日线互不干扰：日线集合未被创建数据
    daily = await inject_sim_db[
        get_collection_name("daily_quotes", "CN")
    ].find({}).to_list(length=1)
    assert daily == []
