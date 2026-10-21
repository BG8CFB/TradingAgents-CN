"""QmtAdapter 单测 — datadir 原始帧 → 标准 Schema 映射（PRD D-5 格式一致性）。

语义基准（技术方案 V-1/V-2）：symbol 裸 6 位、volume 手→股 ×100、amount
直存元、trade_date 'YYYY-MM-DD'、data_source='qmt'。与 TushareCNAdapter
同构（对齐 tests/data/test_adapters_cn.py 风格）。
"""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.data.sources.cn.qmt.adapter import QmtAdapter

TZ = timezone(timedelta(hours=8))


def _ms(y: int, m: int, d: int) -> int:
    return int(datetime(y, m, d, tzinfo=TZ).timestamp() * 1000)


def _daily_raw() -> pd.DataFrame:
    """模拟 QmtProvider.get_daily_quotes 输出（原始列 + ts_code 注入）。"""
    return pd.DataFrame({
        "ts_code": ["000001.SZ"] * 3,
        "time": [_ms(2026, 9, 7), _ms(2026, 9, 8), _ms(2026, 9, 9)],
        "open": [10.0, 10.5, 11.5],
        "high": [11.0, 12.0, 13.0],
        "low": [9.5, 10.2, 11.0],
        "close": [10.5, 11.5, 12.5],
        "volume": [1000, 2000, 3000],           # 手
        "amount": [10_500_000, 23_000_000, 37_500_000],  # 元（直存）
        "preClose": [9.8, 10.5, 11.5],
        "adj_f_evt": [1.0, 1.0, 1.0],
        "adj_f_cum": [106.55, 106.55, 107.62],
    })


class TestAdaptDailyQuotes:
    def setup_method(self):
        self.adapter = QmtAdapter()
        self.results = self.adapter.adapt_daily_quotes(_daily_raw())

    def test_row_count_and_identity(self):
        assert len(self.results) == 3
        r = self.results[0]
        assert r.symbol == "000001"
        assert r.market == "CN"
        assert r.data_source == "qmt"
        assert r.period == "daily"

    def test_volume_lot_to_share(self):
        """V-2：手 → 股 ×100。"""
        assert self.results[0].volume == pytest.approx(100_000.0)
        assert self.results[2].volume == pytest.approx(300_000.0)

    def test_amount_passthrough_yuan(self):
        """QMT amount 直存元，不再 ×1000（区别于 tushare 千元口径）。"""
        assert self.results[0].amount == pytest.approx(10_500_000)

    def test_trade_date_format(self):
        assert self.results[0].trade_date == "2026-09-07"
        assert self.results[2].trade_date == "2026-09-09"

    def test_change_pct_chg_computed(self):
        r = self.results[1]  # close 11.5 / pre_close 10.5
        assert r.change == pytest.approx(1.0)
        assert r.pct_chg == pytest.approx(round((11.5 - 10.5) / 10.5 * 100, 4))

    def test_turnover_rate_none(self):
        """datadir 无流通股本 → 置 None（to_db_doc 过滤，不污染库）。"""
        assert self.results[0].turnover_rate is None
        doc = self.results[0].to_db_doc()
        assert "turnover_rate" not in doc
        assert doc["data_source"] == "qmt"
        assert "updated_at" in doc

    def test_empty_raw(self):
        assert self.adapter.adapt_daily_quotes(pd.DataFrame()) == []


class TestAdaptBasicInfo:
    def test_symbol_and_exchange(self):
        raw = pd.DataFrame({"ts_code": ["000001.SZ", "600000.SH"]})
        results = QmtAdapter().adapt_basic_info(raw)
        assert [r.symbol for r in results] == ["000001", "600000"]
        assert [r.exchange for r in results] == ["SZSE", "SSE"]
        assert results[1].full_symbol == "600000.SSE"
        assert results[0].currency == "CNY"

    def test_metadata_none_not_overwrite(self):
        """name/list_date 置 None：to_db_doc 不含这些键，upsert 不覆盖既有源元数据（FR-05）。"""
        raw = pd.DataFrame({"ts_code": ["000001.SZ"]})
        doc = QmtAdapter().adapt_basic_info(raw)[0].to_db_doc()
        assert "name" not in doc
        assert "list_date" not in doc
        assert doc["exchange"] == "SZSE"


class TestAdaptTradeCalendar:
    def test_calendar_rows(self):
        raw = pd.DataFrame({
            "exchange": ["SSE", "SSE"],
            "cal_date": ["2026-09-07", "2026-09-08"],
            "is_open": [1, 1],
            "pretrade_date": [None, "2026-09-07"],
        })
        results = QmtAdapter().adapt_trade_calendar(raw)
        assert len(results) == 2
        assert results[0].symbol == "__calendar__"
        assert results[0].data_source == "qmt"
        assert results[1].cal_date == "2026-09-08"
        assert results[1].pretrade_date == "2026-09-07"
        assert results[1].is_open is True


class TestAdaptAdjFactors:
    def test_adj_factor_from_cum(self):
        raw = _daily_raw()
        results = QmtAdapter().adapt_adj_factors(raw)
        assert len(results) == 3
        r = results[2]
        assert r.symbol == "000001"
        assert r.trade_date == "2026-09-09"
        assert r.adj_factor == pytest.approx(107.62)  # adj_f_cum 槽位
        assert r.fore_adj_factor is None              # QMT 无对应槽（V-3）
        assert r.back_adj_factor is None

    def test_missing_factor_column(self):
        raw = _daily_raw().drop(columns=["adj_f_cum"])
        assert QmtAdapter().adapt_adj_factors(raw) == []
