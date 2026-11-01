"""Tushare 指数 adapter 单测（DataFrame 字面量喂真实 adapt_index_quotes，无网络）。"""

import pandas as pd

from app.data.sources.cn.tushare.adapter import TushareCNAdapter


def _df(rows):
    return pd.DataFrame(rows)


class TestAdaptIndexQuotes:
    def test_symbol_passthrough_and_unit_conversion(self):
        df = _df(
            [
                {
                    "ts_code": "000300.SH",
                    "trade_date": "20260105",
                    "open": 4000.0,
                    "high": 4010.0,
                    "low": 3995.0,
                    "close": 4005.0,
                    "pre_close": 3998.0,
                    "change": 7.0,
                    "pct_chg": 0.18,
                    "volume": 12345.0,   # 手
                    "amount": 5678.0,    # 千元
                }
            ]
        )
        out = TushareCNAdapter().adapt_index_quotes(df)
        assert len(out) == 1
        rec = out[0]
        # ts_code 原样保留为指数规范码（不剥后缀）
        assert rec.symbol == "000300.SH"
        assert rec.trade_date == "2026-01-05"
        assert rec.close == 4005.0
        assert rec.open == 4000.0
        assert rec.volume == 1234500.0   # 手 → 股
        assert rec.amount == 5678000.0   # 千元 → 元
        assert rec.data_source == "tushare"
        assert rec.market == "CN"

    def test_derives_change_when_missing(self):
        df = _df(
            [
                {
                    "ts_code": "399006.SZ",
                    "trade_date": "20260105",
                    "open": 2100.0,
                    "high": 2110.0,
                    "low": 2090.0,
                    "close": 2100.0,
                    "pre_close": 2000.0,
                }
            ]
        )
        rec = TushareCNAdapter().adapt_index_quotes(df)[0]
        assert rec.change == 100.0
        assert rec.pct_chg == 5.0

    def test_empty_and_missing_keys_skipped(self):
        assert TushareCNAdapter().adapt_index_quotes(pd.DataFrame()) == []
        df = _df(
            [
                {"ts_code": "", "trade_date": "20260105"},        # 无 symbol → 跳过
                {"ts_code": "HSI", "trade_date": None},           # 无日期 → 跳过
                {"ts_code": "HSI", "trade_date": "20260105"},     # 合法
            ]
        )
        out = TushareCNAdapter().adapt_index_quotes(df)
        assert len(out) == 1
        assert out[0].symbol == "HSI"
