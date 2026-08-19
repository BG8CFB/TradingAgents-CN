"""测试 A 股三源适配器 — 字段映射、单位转换、空值处理。"""

import pandas as pd
import numpy as np

from app.data.sources.cn.tushare.adapter import TushareCNAdapter
from app.data.sources.cn.akshare.adapter import AKShareCNAdapter
from app.data.sources.cn.baostock.adapter import BaoStockCNAdapter


class TestTushareCNAdapter:
    def setup_method(self):
        self.adapter = TushareCNAdapter()

    def test_adapt_basic_info(self):
        df = pd.DataFrame([{
            "ts_code": "000001.SZ", "symbol": "000001", "name": "平安银行",
            "area": "广东", "industry": "银行", "market": "主板",
            "list_status": "L", "list_date": 19910403,
        }])
        results = self.adapter.adapt_basic_info(df)
        assert len(results) == 1
        r = results[0]
        assert r.symbol == "000001"
        assert r.market == "CN"
        assert r.data_source == "tushare"
        assert r.name == "平安银行"
        assert r.exchange == "SZSE"
        assert r.list_date == "1991-04-03"

    def test_adapt_daily_quotes_unit_conversion(self):
        """Tushare: 手→股(×100), 千元→元(×1000)。"""
        df = pd.DataFrame([{
            "ts_code": "600000.SH", "trade_date": 20240115,
            "open": 10.0, "high": 11.0, "low": 9.5, "close": 10.5,
            "pre_close": 10.0, "change": 0.5, "pct_chg": 5.0,
            "vol": 1000,  # 手
            "amount": 500,  # 千元
        }])
        results = self.adapter.adapt_daily_quotes(df)
        assert len(results) == 1
        r = results[0]
        assert r.symbol == "600000"
        assert r.volume == 100000  # 1000手 × 100
        assert r.amount == 500000  # 500千元 × 1000
        assert r.trade_date == "2024-01-15"

    def test_adapt_daily_indicators_unit_conversion(self):
        """Tushare: 万元→元(×10000)。"""
        df = pd.DataFrame([{
            "ts_code": "000001.SZ", "trade_date": 20240115,
            "pe": 5.5, "pb": 0.8, "ps": 1.2,
            "total_mv": 100000,  # 万元
            "circ_mv": 80000,
        }])
        results = self.adapter.adapt_daily_indicators(df)
        assert len(results) == 1
        r = results[0]
        assert r.total_mv == 100000 * 10000
        assert r.circ_mv == 80000 * 10000

    def test_adapt_empty_df(self):
        df = pd.DataFrame()
        assert self.adapter.adapt_basic_info(df) == []
        assert self.adapter.adapt_daily_quotes(df) == []

    def test_adapt_null_values(self):
        df = pd.DataFrame([{
            "ts_code": "000001.SZ", "trade_date": 20240115,
            "open": np.nan, "high": None, "low": "",
            "close": 10.0, "vol": 100, "amount": np.nan,
        }])
        results = self.adapter.adapt_daily_quotes(df)
        assert len(results) == 1
        r = results[0]
        assert r.open is None
        assert r.high is None
        assert r.amount is None
        assert r.close == 10.0


class TestAKShareCNAdapter:
    def setup_method(self):
        self.adapter = AKShareCNAdapter()

    def test_adapt_basic_info(self):
        df = pd.DataFrame([{
            "code": "000001", "name": "平安银行",
            "industry": "银行", "area": "广东",
        }])
        results = self.adapter.adapt_basic_info(df)
        assert len(results) == 1
        r = results[0]
        assert r.symbol == "000001"
        assert r.data_source == "akshare"
        assert r.exchange == "SZSE"

    def test_adapt_daily_quotes_no_conversion(self):
        """AKShare 数据已是标准单位，无需转换。"""
        df = pd.DataFrame([{
            "code": "000001", "trade_date": "2024-01-15",
            "open": 10.0, "close": 10.5, "high": 11.0, "low": 9.5,
            "volume": 100000, "amount": 1050000,
        }])
        results = self.adapter.adapt_daily_quotes(df)
        assert len(results) == 1
        assert results[0].volume == 100000
        assert results[0].amount == 1050000

    def test_adapt_daily_quotes_symbol_injected(self):
        """东财接口 df 无代码列，API 层注入 symbol 后 adapter 必须正确落 symbol。

        回归：600519 分析失败 — symbol 缺失时被写成 "000000"，
        导致入库后按真实代码回读为空，任务判定"无法获取历史数据"。
        """
        df = pd.DataFrame([{
            "symbol": "600519", "日期": "2024-01-15",
            "开盘": 1700.0, "收盘": 1710.0, "最高": 1720.0, "最低": 1690.0,
            "成交量": 30000, "成交额": 51000000,
        }])
        results = self.adapter.adapt_daily_quotes(df)
        assert len(results) == 1
        assert results[0].symbol == "600519"

    def test_adapt_daily_quotes_missing_symbol_skipped(self):
        """df 既无 symbol 也无 code 列时，不得静默产出 symbol='000000' 的脏记录。"""
        df = pd.DataFrame([{
            "日期": "2024-01-15",
            "开盘": 1700.0, "收盘": 1710.0, "最高": 1720.0, "最低": 1690.0,
            "成交量": 30000, "成交额": 51000000,
        }])
        assert self.adapter.adapt_daily_quotes(df) == []


class TestBaoStockCNAdapter:
    def setup_method(self):
        self.adapter = BaoStockCNAdapter()

    def test_adapt_daily_quotes(self):
        df = pd.DataFrame([{
            "code": "sh.600000", "trade_date": "2024-01-15",
            "open": 10.0, "close": 10.5, "high": 11.0, "low": 9.5,
            "volume": 100000, "amount": 1050000,
        }])
        results = self.adapter.adapt_daily_quotes(df)
        assert len(results) == 1
        r = results[0]
        assert r.symbol == "600000"
        assert r.volume == 100000

    def test_adapt_basic_info_dot_code(self):
        df = pd.DataFrame([{
            "code": "sh.600000", "name": "浦发银行",
            "industry": "银行",
        }])
        results = self.adapter.adapt_basic_info(df)
        assert len(results) == 1
        assert results[0].symbol == "600000"
        assert results[0].exchange == "SSE"
