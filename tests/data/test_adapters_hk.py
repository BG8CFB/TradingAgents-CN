"""测试港股适配器 — 5 位代码补零、HKD、公司行为。"""

import pytest
import pandas as pd

from app.data.sources.hk.akshare_hk.adapter import AKShareHKAdapter
from app.data.sources.hk.yfinance_hk.adapter import YFinanceHKAdapter
from app.data.sources.hk.tushare_hk.adapter import TushareHKAdapter
from app.data.sources.hk.tencent_hk.adapter import TencentHKAdapter


class TestAKShareHKAdapter:
    def setup_method(self):
        self.adapter = AKShareHKAdapter()

    def test_adapt_basic_info_5digit(self):
        df = pd.DataFrame([{
            "代码": "00700", "名称": "腾讯控股",
            "所属行业": "互联网",
        }])
        results = self.adapter.adapt_basic_info(df)
        assert len(results) == 1
        r = results[0]
        assert r.symbol == "00700"
        assert r.market == "HK"
        assert r.exchange == "HKEX"
        assert r.currency == "HKD"

    def test_adapt_corporate_actions(self):
        df = pd.DataFrame([{
            "代码": "00700", "除净日": "2024-05-15",
            "类型": "分红", "派息": 2.5,
        }])
        results = self.adapter.adapt_corporate_actions(df)
        assert len(results) == 1
        r = results[0]
        assert r.action_type == "cash_dividend"
        assert r.amount == 2.5
        assert r.currency == "HKD"

    def test_adapt_bonus_issue(self):
        df = pd.DataFrame([{
            "代码": "01234", "除净日": "2024-06-01",
            "类型": "红股", "送股比例": 0.1,
        }])
        results = self.adapter.adapt_corporate_actions(df)
        assert len(results) == 1
        assert results[0].action_type == "bonus_issue"

    def test_adapt_rights_issue(self):
        df = pd.DataFrame([{
            "代码": "05678", "除净日": "2024-07-01",
            "类型": "供股", "供股价": 5.0,
        }])
        results = self.adapter.adapt_corporate_actions(df)
        assert len(results) == 1
        assert results[0].action_type == "rights_issue"
        assert results[0].rights_price == 5.0


class TestTushareHKAdapter:
    def setup_method(self):
        self.adapter = TushareHKAdapter()

    def test_5digit_ts_code(self):
        df = pd.DataFrame([{
            "ts_code": "00700.HK", "name": "腾讯控股",
            "industry": "Software",
        }])
        results = self.adapter.adapt_basic_info(df)
        assert len(results) == 1
        assert results[0].symbol == "00700"
        assert results[0].full_symbol == "00700.HK"

    def test_adapt_daily_quotes(self):
        df = pd.DataFrame([{
            "ts_code": "00700.HK", "trade_date": 20240115,
            "open": 300.0, "close": 310.0, "high": 315.0, "low": 295.0,
            "vol": 10000000, "amount": 3100000000,
        }])
        results = self.adapter.adapt_daily_quotes(df)
        assert len(results) == 1
        assert results[0].symbol == "00700"
        assert results[0].close == 310.0


class TestTencentHKAdapter:
    def setup_method(self):
        self.adapter = TencentHKAdapter()

    def test_adapt_market_quotes(self):
        df = pd.DataFrame([{
            "symbol": "700", "price": 310.0, "volume": 10000000,
            "bid": 309.8, "ask": 310.2, "update_time": "2024-01-15 14:30:00",
        }])
        results = self.adapter.adapt_market_quotes(df)
        assert len(results) == 1
        r = results[0]
        assert r.symbol == "00700"
        assert r.quote_source_type == "realtime"
        assert r.bid_price == 309.8
        assert r.ask_price == 310.2
