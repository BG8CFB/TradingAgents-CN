"""QmtDatadirReader 本地直读器单测（移植自 StockQuant test_datadir_reader.py，2026-10）。

不依赖真实 datadir：用 struct.pack 合成小 .DAT/.dat 文件构造 datadir 目录，
精确控制哨兵/记录/半写/损坏等场景。这些二进制 fixture 用例是格式正确性的
唯一回归保障（原仓库事故史见 datadir_reader 模块 docstring），随代码移植。
移植改动：import 路径（app.data.sources.cn.qmt）；追加 TestSelfCheck
（聚合自检为移植期新增能力）。
"""
from __future__ import annotations

import struct
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.data.sources.cn.qmt.datadir_reader import (
    KLINE_HEADER_SENTINEL,
    QmtDatadirReader,
)

TZ = timezone(timedelta(hours=8))


def _day_sec(y: int, m: int, d: int, hh: int = 0, mm: int = 0) -> int:
    """北京时区时刻 → unix 秒（合成记录的 ts）。"""
    return int(datetime(y, m, d, hh, mm, tzinfo=TZ).timestamp())


def _pack_kline(
    ts: int, o: float, h: float, lo: float, c: float,
    vol: int, amount: int, pre_close: float,
    *, status: int = 544, open_interest: int = 15, tail: int = 32765,
) -> bytes:
    """合成一条 64B K线记录（小端，布局见模块 docstring）。"""
    return struct.pack(
        '<8I Q I f f 3I',
        ts,
        int(o * 1000), int(h * 1000), int(lo * 1000), int(c * 1000),
        0, vol, status,
        amount, open_interest, 1.0, 107.62,
        int(pre_close * 1000), 0, tail,
    )


def _write_kline_file(path: Path, records: list[bytes], *, header: int = KLINE_HEADER_SENTINEL) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack('<q', header) + b''.join(records))


def _pack_tick(
    raw_ts: int, last: float, amount: int, vol: int, phase: int,
    last_close: float,
    ask_p: tuple = (0.0,) * 5, ask_v: tuple = (0,) * 5,
    bid_p: tuple = (0.0,) * 5, bid_v: tuple = (0,) * 5,
) -> bytes:
    """合成一条 144B tick 记录（36 × u4）。"""
    return struct.pack(
        '<36I',
        raw_ts, 0, int(last * 1000), 0, amount, 0, vol, phase,
        0, 0, 0, 0, 0, 0, 0, int(last_close * 1000),
        *[int(p * 1000) for p in ask_p], *ask_v,
        *[int(p * 1000) for p in bid_p], *bid_v,
    )


def _three_days_records() -> list[bytes]:
    """20260907~0909 三条连续日线（preClose 链完整）。"""
    return [
        _pack_kline(_day_sec(2026, 9, 7), 10.0, 11.0, 9.5, 10.5, 1000, 10_500_000, 9.8),
        _pack_kline(_day_sec(2026, 9, 8), 10.5, 12.0, 10.2, 11.5, 2000, 23_000_000, 10.5),
        _pack_kline(_day_sec(2026, 9, 9), 11.5, 13.0, 11.0, 12.5, 3000, 37_500_000, 11.5),
    ]


def _recent_records(days_ago: list[int]) -> list[bytes]:
    """以「今天」为锚的连续日线（preClose 链完整；健康探针 OK 路径用，
    避免固定历史日期触发停更判定）。"""
    today = date.today()
    out: list[bytes] = []
    prev_close = 10.0
    for i, ago in enumerate(days_ago):
        d = today - timedelta(days=ago)
        c = prev_close + 0.5
        out.append(_pack_kline(
            _day_sec(d.year, d.month, d.day),
            prev_close - 0.2, c + 0.5, prev_close - 0.5, c,
            1000 * (i + 1), 10_000_000 * (i + 1), prev_close,
        ))
        prev_close = c
    return out


def _yyyymmdd(d: date) -> str:
    return d.strftime('%Y%m%d')


class TestKlineParse:
    """K线解析：正确性 + 漏尾陷阱回归 + 自检拒读"""

    def _mk(self, tmp_path: Path) -> QmtDatadirReader:
        _write_kline_file(tmp_path / 'SZ' / '86400' / '000001.DAT', _three_days_records())
        return QmtDatadirReader(str(tmp_path))

    def test_daily_rows_and_values(self, tmp_path):
        """3 条记录必须出 3 行（qmt-parser 偏移陷阱回归：最后一条=当日收盘 bar 不得丢）。"""
        df = self._mk(tmp_path).daily('000001.SZ')
        assert df is not None and len(df) == 3
        last = df.iloc[-1]
        assert last['close'] == pytest.approx(12.5)
        assert last['open'] == pytest.approx(11.5)
        assert last['preClose'] == pytest.approx(11.5)
        assert last['volume'] == 3000
        assert last['amount'] == pytest.approx(37_500_000)
        assert last['suspendFlag'] == 0
        assert last['openInterest'] == 15  # [40:44] 槽位 → 现库 openInterest 列

    def test_daily_time_contract(self, tmp_path):
        """time=ms epoch → 北京时区转换 → trade_date 正确（adapter 映射基准）。"""
        df = self._mk(tmp_path).daily('000001.SZ')
        dt = (
            df['time'].astype('int64')
            .map(lambda ms: datetime.fromtimestamp(ms / 1000, TZ))
        )
        assert dt.iloc[0].strftime('%Y%m%d') == '20260907'
        assert dt.iloc[-1].strftime('%Y%m%d') == '20260909'
        assert dt.iloc[-1].hour == 0 and dt.iloc[-1].minute == 0  # 日线=当日 00:00

    def test_daily_date_filter_inclusive(self, tmp_path):
        reader = self._mk(tmp_path)
        df = reader.daily('000001.SZ', start='20260908', end='20260908')
        assert len(df) == 1
        assert df.iloc[0]['close'] == pytest.approx(11.5)
        assert reader.daily('000001.SZ', start='20261001') is not None
        assert len(reader.daily('000001.SZ', start='20261001')) == 0

    def test_daily_missing_file(self, tmp_path):
        assert QmtDatadirReader(str(tmp_path)).daily('000001.SZ') is None

    def test_header_sentinel_reject(self, tmp_path):
        _write_kline_file(
            tmp_path / 'SZ' / '86400' / '000001.DAT',
            _three_days_records(), header=0x12345678,
        )
        assert QmtDatadirReader(str(tmp_path)).daily('000001.SZ') is None

    def test_tail_sentinel_not_validated(self, tmp_path):
        """2026-09-23 决策：尾哨兵不再校验——任意取值（含 0）都必须可读。"""
        recs = _three_days_records()
        bad = _pack_kline(_day_sec(2026, 9, 9), 11.5, 13.0, 11.0, 12.5, 3000, 1, 11.5, tail=0)
        _write_kline_file(tmp_path / 'SZ' / '86400' / '000001.DAT', recs[:2] + [bad])
        df = QmtDatadirReader(str(tmp_path)).daily('000001.SZ')
        assert df is not None
        assert len(df) == 3

    def test_status_nonuniform_reject(self, tmp_path):
        """status 必须文件级全等：混入不同值 → 记录错位/漂移，拒读。"""
        recs = _three_days_records()
        bad = _pack_kline(_day_sec(2026, 9, 9), 11.5, 13.0, 11.0, 12.5, 3000, 1, 11.5, status=440)
        _write_kline_file(tmp_path / 'SZ' / '86400' / '000001.DAT', recs[:2] + [bad])
        assert QmtDatadirReader(str(tmp_path)).daily('000001.SZ') is None

    def test_status_out_of_bound_reject(self, tmp_path):
        """status 量级上界：错位读价格/amount 高位 → 超界拒读。"""
        recs = [
            _pack_kline(_day_sec(2026, 9, 8), 10.5, 12.0, 10.2, 11.5, 2000, 1, 10.5,
                        status=999_999_999),
            _pack_kline(_day_sec(2026, 9, 9), 11.5, 13.0, 11.0, 12.5, 3000, 1, 11.5,
                        status=999_999_999),
        ]
        _write_kline_file(tmp_path / 'SZ' / '86400' / '000001.DAT', recs)
        assert QmtDatadirReader(str(tmp_path)).daily('000001.SZ') is None

    def test_status_vintage_drift_accept(self, tmp_path):
        """status 值随数据批次漂移（实测 440/544 均合法）：文件级全等即接受。"""
        recs = [
            _pack_kline(_day_sec(2026, 9, 8), 10.5, 12.0, 10.2, 11.5, 2000, 23_000_000, 10.5,
                        status=440),
            _pack_kline(_day_sec(2026, 9, 9), 11.5, 13.0, 11.0, 12.5, 3000, 37_500_000, 11.5,
                        status=440),
        ]
        _write_kline_file(tmp_path / 'SZ' / '86400' / '000001.DAT', recs)
        df = QmtDatadirReader(str(tmp_path)).daily('000001.SZ')
        assert df is not None and len(df) == 2

    def test_ts_not_monotonic_reject(self, tmp_path):
        recs = [
            _pack_kline(_day_sec(2026, 9, 8), 10.5, 12.0, 10.2, 11.5, 2000, 1, 10.5),
            _pack_kline(_day_sec(2026, 9, 7), 10.0, 11.0, 9.5, 10.5, 1000, 1, 9.8),
        ]
        _write_kline_file(tmp_path / 'SZ' / '86400' / '000001.DAT', recs)
        assert QmtDatadirReader(str(tmp_path)).daily('000001.SZ') is None

    def test_half_written_tail_truncated(self, tmp_path):
        """QMT 运行中半写尾记录：截断为整记录（3 条 + 半条 → 3 行）。"""
        path = tmp_path / 'SZ' / '86400' / '000001.DAT'
        full = struct.pack('<q', KLINE_HEADER_SENTINEL) + b''.join(_three_days_records())
        path.parent.mkdir(parents=True)
        path.write_bytes(full + b'\x00' * 20)  # 20B 半写尾巴（非 64 整数倍）
        df = QmtDatadirReader(str(tmp_path)).daily('000001.SZ')
        assert df is not None and len(df) == 3

    def test_preclose_chain_gap_only_warns(self, tmp_path, caplog):
        """preClose 链断裂=历史缺记录的合法形态：仅告警，不拒读。"""
        recs = [
            _pack_kline(_day_sec(2026, 9, 7), 10.0, 11.0, 9.5, 10.5, 1000, 1, 9.8),
            # ts 跳到 0909（缺 0908），preClose=0908 收盘 → 与前条 close 不等
            _pack_kline(_day_sec(2026, 9, 9), 11.5, 13.0, 11.0, 12.5, 3000, 1, 11.5),
        ]
        _write_kline_file(tmp_path / 'SZ' / '86400' / '000001.DAT', recs)
        with caplog.at_level('WARNING'):
            df = QmtDatadirReader(str(tmp_path)).daily('000001.SZ')
        assert df is not None and len(df) == 2
        assert any('preClose 链断裂' in r.message for r in caplog.records)

    def test_increment_file_warning(self, tmp_path, caplog):
        """增量文件（_4002）非零：告警但不影响主文件解析。"""
        self._mk(tmp_path)
        inc = tmp_path / 'SZ' / '86400' / '000001_4002.DAT'
        inc.write_bytes(b'\x01' * 64)
        with caplog.at_level('WARNING'):
            df = QmtDatadirReader(str(tmp_path)).daily('000001.SZ')
        assert df is not None and len(df) == 3
        assert any('增量文件非零' in r.message for r in caplog.records)

    def test_minute_5m_bar_time(self, tmp_path):
        """5min 走 300/ 目录，ts=bar 时刻秒（非当日 00:00）。"""
        _write_kline_file(tmp_path / 'SZ' / '300' / '000001.DAT', [
            _pack_kline(_day_sec(2026, 9, 9, 14, 55), 12.0, 12.4, 11.9, 12.3, 500, 1, 12.0),
            _pack_kline(_day_sec(2026, 9, 9, 15, 0), 12.3, 12.6, 12.2, 12.5, 800, 1, 12.3),
        ])
        df = QmtDatadirReader(str(tmp_path)).minute('000001.SZ', '5m')
        assert df is not None and len(df) == 2
        last_dt = datetime.fromtimestamp(int(df.iloc[-1]['time']) / 1000, TZ)
        assert (last_dt.hour, last_dt.minute) == (15, 0)

    def test_bj_unsupported(self, tmp_path):
        """BJ 无本地实证 → None（本项目语义：走回退链接管）。"""
        assert self._mk(tmp_path).daily('870001.BJ') is None
        assert self._mk(tmp_path).tick('870001.BJ', '20260909') is None


class TestTickParse:
    """tick 解析：144B 布局 / 基自校准 / 竞价相位列 / 5 档形态"""

    def _mk(self, tmp_path: Path, records: list[bytes], trade_date: str = '20260909') -> QmtDatadirReader:
        path = tmp_path / 'SZ' / '0' / '000001' / f'{trade_date}.dat'
        path.parent.mkdir(parents=True)
        path.write_bytes(b''.join(records))
        return QmtDatadirReader(str(tmp_path))

    def test_tick_calibration_and_fields(self, tmp_path):
        """首条竞价行锚定 09:15:00.000；连续竞价行时间线性推进；5 档为 5 元素 list。"""
        base = 400_000_000  # 任意基偏移（基值随日期变化，自校准须不依赖常量）
        reader = self._mk(tmp_path, [
            _pack_tick(base, 0.0, 0, 0, 12, 11.5,
                       ask_p=(11.6, 11.7, 0, 0, 0), ask_v=(100, 200, 0, 0, 0),
                       bid_p=(11.4, 11.3, 0, 0, 0), bid_v=(50, 60, 0, 0, 0)),
            _pack_tick(base + 60_000, 11.55, 115_500, 10_000, 15, 11.5),
        ])
        df = reader.tick('000001.SZ', '20260909')
        assert df is not None and len(df) == 2
        t0 = datetime.fromtimestamp(int(df.iloc[0]['time']) / 1000, TZ)
        t1 = datetime.fromtimestamp(int(df.iloc[1]['time']) / 1000, TZ)
        assert (t0.hour, t0.minute, t0.second) == (9, 15, 0)      # 竞价锚点
        assert (t1.hour, t1.minute, t1.second) == (9, 16, 0)      # +60s 线性
        assert df.iloc[0]['market_phase_status'] == 12
        assert df.iloc[1]['market_phase_status'] == 15
        assert df.iloc[1]['lastPrice'] == pytest.approx(11.55)
        assert df.iloc[1]['lastClose'] == pytest.approx(11.5)
        assert df.iloc[1]['volume'] == 10_000
        # 5 档：list 形态 + 数值
        assert list(df.iloc[0]['askPrice']) == pytest.approx([11.6, 11.7, 0.0, 0.0, 0.0])
        assert list(df.iloc[0]['bidVol']) == [50, 60, 0, 0, 0]
        # 现库 schema 占位列存在
        for col in ('open', 'high', 'low', 'pvolume', 'transactionNum'):
            assert col in df.columns

    def test_tick_no_auction_reject(self, tmp_path, caplog):
        """无竞价行：拒读返回 None（时间基不可校准，相对时刻落库会错语义）。"""
        base = 400_000_000
        reader = self._mk(tmp_path, [
            _pack_tick(base, 11.5, 1000, 100, 15, 11.4),
            _pack_tick(base + 3_600_000, 11.6, 2000, 200, 15, 11.4),
        ])
        with caplog.at_level('WARNING'):
            df = reader.tick('000001.SZ', '20260909')
        assert df is None
        assert any('无竞价行' in r.message for r in caplog.records)

    def test_tick_missing_and_empty(self, tmp_path):
        assert QmtDatadirReader(str(tmp_path)).tick('000001.SZ', '20260909') is None
        path = tmp_path / 'SZ' / '0' / '000001' / '20260909.dat'
        path.parent.mkdir(parents=True)
        path.write_bytes(b'\x00' * 100)  # 不足一条
        assert QmtDatadirReader(str(tmp_path)).tick('000001.SZ', '20260909') is None


class TestHasDaily:
    """存在性位图（对账用）"""

    def test_has_daily_bitmap(self, tmp_path):
        _write_kline_file(tmp_path / 'SZ' / '86400' / '000001.DAT', _three_days_records())
        reader = QmtDatadirReader(str(tmp_path))
        got = reader.has_daily('000001.SZ', ['20260905', '20260907', '20260908', '20260909', '20260910'])
        assert list(got) == [False, True, True, True, False]

    def test_has_daily_missing_file_all_false(self, tmp_path):
        reader = QmtDatadirReader(str(tmp_path))
        assert list(reader.has_daily('000001.SZ', ['20260909'])) == [False]

    def test_has_daily_rejected_file_all_false(self, tmp_path):
        _write_kline_file(
            tmp_path / 'SZ' / '86400' / '000001.DAT',
            _three_days_records(), header=0x12345678,
        )
        reader = QmtDatadirReader(str(tmp_path))
        assert list(reader.has_daily('000001.SZ', ['20260909'])) == [False]


class TestMisc:
    def test_available(self, tmp_path):
        assert QmtDatadirReader(str(tmp_path)).available is True
        assert QmtDatadirReader(str(tmp_path / 'not_exist')).available is False

    def test_split_code(self):
        assert QmtDatadirReader.split_code('000001.SZ') == ('SZ', '000001')
        assert QmtDatadirReader.split_code('600000.SH') == ('SH', '600000')
        assert QmtDatadirReader.split_code('870001.BJ') is None
        assert QmtDatadirReader.split_code('bad') is None

    def test_minute_invalid_period(self, tmp_path):
        with pytest.raises(ValueError):
            QmtDatadirReader(str(tmp_path)).minute('000001.SZ', '15m')


class TestStockCodesAndCalendar:
    """代码枚举与交易日历（stock_codes 前缀白名单 / 上证指数派生日历）"""

    def test_stock_codes_prefix_filter(self, tmp_path):
        # SH/000001.DAT（指数）不入宇宙；SH/600000.DAT、SZ/000001.DAT 入
        _write_kline_file(tmp_path / 'SH' / '86400' / '000001.DAT', _three_days_records())
        _write_kline_file(tmp_path / 'SH' / '86400' / '600000.DAT', _three_days_records())
        _write_kline_file(tmp_path / 'SZ' / '86400' / '000001.DAT', _three_days_records())
        _write_kline_file(tmp_path / 'SH' / '86400' / 'index_meta.DAT', _three_days_records())
        codes = QmtDatadirReader(str(tmp_path)).stock_codes()
        assert codes == ['000001.SZ', '600000.SH']

    def test_trading_dates_from_index(self, tmp_path):
        _write_kline_file(tmp_path / 'SH' / '86400' / '000001.DAT', _three_days_records())
        dates = QmtDatadirReader(str(tmp_path)).trading_dates()
        assert dates == ['20260907', '20260908', '20260909']

    def test_trading_dates_missing(self, tmp_path):
        assert QmtDatadirReader(str(tmp_path)).trading_dates() is None


class TestSelfCheck:
    """聚合自检（移植期新增）：OK / 停更 / 自检拒读 / 路径缺失"""

    def _mk_fresh(self, tmp_path: Path) -> QmtDatadirReader:
        """以「今天」为锚的就绪 datadir：指数 + 两只股票。"""
        recs = _recent_records([2, 1, 0])
        _write_kline_file(tmp_path / 'SH' / '86400' / '000001.DAT', recs)
        _write_kline_file(tmp_path / 'SZ' / '86400' / '000001.DAT', recs)
        _write_kline_file(tmp_path / 'SH' / '86400' / '600000.DAT', recs)
        return QmtDatadirReader(str(tmp_path))

    def test_self_check_ok(self, tmp_path):
        report = self._mk_fresh(tmp_path).self_check()
        assert report.ok is True
        assert report.path_missing is False
        assert report.universe_size == 2
        assert report.checked_files == 2
        assert report.rejected_samples == []
        assert report.latest_trade_date == _yyyymmdd(date.today())

    def test_self_check_old_dates_parse_ok(self, tmp_path):
        """self_check 只负责「文件可解析」：固定历史日期不拒读、如实上报最新分区。

        停更判定属健康探针层（见 test_qmt_health.py::TestProbeStates::test_stale）。
        """
        _write_kline_file(tmp_path / 'SH' / '86400' / '000001.DAT', _three_days_records())
        _write_kline_file(tmp_path / 'SZ' / '86400' / '000001.DAT', _three_days_records())
        report = QmtDatadirReader(str(tmp_path)).self_check()
        assert report.ok is True
        assert report.latest_trade_date == '20260909'
        assert report.rejected_samples == []

    def test_self_check_rejects_corrupt_file(self, tmp_path):
        recs = _recent_records([2, 1, 0])
        # 600000 文件尾日 status 混入异值 → 四级自检拒读
        today = date.today()
        bad = _pack_kline(
            _day_sec(today.year, today.month, today.day),
            10.5, 11.0, 10.4, 10.8, 1000, 1, 10.5, status=440,
        )
        _write_kline_file(tmp_path / 'SH' / '86400' / '000001.DAT', recs)
        _write_kline_file(tmp_path / 'SZ' / '86400' / '000001.DAT', recs)
        _write_kline_file(tmp_path / 'SH' / '86400' / '600000.DAT', recs[:2] + [bad])
        report = QmtDatadirReader(str(tmp_path)).self_check()
        assert report.ok is False
        assert '600000.SH' in report.rejected_samples

    def test_self_check_path_missing(self, tmp_path):
        report = QmtDatadirReader(str(tmp_path / 'nope')).self_check()
        assert report.ok is False
        assert report.path_missing is True

    def test_self_check_empty_universe(self, tmp_path):
        # 目录存在但只有指数文件（无股票前缀）→ 宇宙为空
        _write_kline_file(tmp_path / 'SH' / '86400' / '000001.DAT', _three_days_records())
        report = QmtDatadirReader(str(tmp_path)).self_check()
        assert report.ok is False
        assert report.universe_size == 0
