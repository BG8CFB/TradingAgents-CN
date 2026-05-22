"""测试美股适配器 — 大写 ticker、adj_close、公司行为。"""

import pytest
import pandas as pd

from app.data.sources.us.yfinance.adapter import YFinanceUSAdapter
from app.data.sources.us.finnhub.adapter import FinnhubUSAdapter
from app.data.sources.us.tushare_us.adapter import TushareUSAdapter
from app.data.sources.us.alpha_vantage.adapter import AlphaVantageUSAdapter


class TestYFinanceUSAdapter:
    def setup_method(self):
        self.adapter = YFinanceUSAdapter()

    def test_adapt_daily_quotes_uppercase(self):
        df = pd.DataFrame([{
            "symbol": "aapl",
        }], index=pd.to_datetime(["2024-01-15"]))
        df["Open"] = 185.0
        df["High"] = 190.0
        df["Low"] = 184.0
        df["Close"] = 188.0
        df["Volume"] = 50000000

        results = self.adapter.adapt_daily_quotes(df)
        assert len(results) == 1
        r = results[0]
        assert r.symbol == "AAPL"
        assert r.close == 188.0
        assert r.trade_date == "2024-01-15"

    def test_adapt_corporate_actions_dividend(self):
        df = pd.DataFrame([{
            "date": "2024-02-15", "action_type": "cash_dividend",
            "amount": 0.24, "symbol": "aapl",
        }])
        results = self.adapter.adapt_corporate_actions(df)
        assert len(results) == 1
        assert results[0].symbol == "AAPL"
        assert results[0].action_type == "cash_dividend"
        assert results[0].amount == 0.24
        assert results[0].currency == "USD"

    def test_adapt_reverse_split(self):
        df = pd.DataFrame([{
            "date": "2024-06-15", "action_type": "reverse_split",
            "ratio": 0.1, "symbol": "TSLA",
        }])
        results = self.adapter.adapt_corporate_actions(df)
        assert len(results) == 1
        assert results[0].action_type == "reverse_split"


class TestFinnhubUSAdapter:
    def setup_method(self):
        self.adapter = FinnhubUSAdapter()

    def test_adapt_basic_info(self):
        df = pd.DataFrame([{
            "symbol": "AAPL", "description": "Apple Inc",
            "exchange": "NASDAQ", "finnhubIndustry": "Technology",
        }])
        results = self.adapter.adapt_basic_info(df)
        assert len(results) == 1
        assert results[0].symbol == "AAPL"
        assert results[0].exchange == "NASDAQ"

    def test_adapt_news(self):
        df = pd.DataFrame([{
            "related": "AAPL", "headline": "Apple Reports Q1",
            "summary": "Strong earnings", "source": "cnbc",
            "url": "https://example.com", "datetime": 1700000000,
        }])
        results = self.adapter.adapt_news(df)
        assert len(results) == 1
        assert results[0].title == "Apple Reports Q1"
        assert results[0].content_hash is not None


class TestTushareUSAdapter:
    def setup_method(self):
        self.adapter = TushareUSAdapter()

    def test_parse_symbol_from_ts_code(self):
        df = pd.DataFrame([{
            "ts_code": "AAPL.O", "name": "Apple Inc",
        }])
        results = self.adapter.adapt_basic_info(df)
        assert len(results) == 1
        assert results[0].symbol == "AAPL"

    def test_adapt_daily_quotes(self):
        df = pd.DataFrame([{
            "ts_code": "MSFT.O", "trade_date": 20240115,
            "open": 380.0, "close": 385.0, "high": 388.0, "low": 379.0,
            "vol": 20000000, "amount": 7700000000,
        }])
        results = self.adapter.adapt_daily_quotes(df)
        assert len(results) == 1
        assert results[0].symbol == "MSFT"


class TestAlphaVantageUSAdapter:
    def setup_method(self):
        self.adapter = AlphaVantageUSAdapter()

    def test_adapt_daily_quotes(self):
        df = pd.DataFrame([{
            "trade_date": "2024-01-15", "symbol": "GOOG",
            "open": "140.0", "close": "142.5", "high": "143.0",
            "low": "139.0", "volume": "30000000",
        }])
        results = self.adapter.adapt_daily_quotes(df)
        assert len(results) == 1
        assert results[0].symbol == "GOOG"
        assert results[0].close == 142.5

    def test_adapt_corporate_actions(self):
        df = pd.DataFrame([{
            "date": "2024-03-15", "action_type": "cash_dividend",
            "amount": 0.5, "symbol": "MSFT",
        }])
        results = self.adapter.adapt_corporate_actions(df)
        assert len(results) == 1
        assert results[0].currency == "USD"
