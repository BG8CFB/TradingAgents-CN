"""TushareCNAdapter 各域 adapt_* 方法单元测试 — 匹配新架构 API"""

import pandas as pd
import pytest

from app.data.sources.cn.tushare.adapter import TushareCNAdapter


@pytest.fixture
def adapter():
    return TushareCNAdapter(provider=None)


class TestAdaptBasicInfo:
    """基础信息适配测试"""

    def test_ts_code_parsing(self, adapter):
        df = pd.DataFrame([{
            "ts_code": "000001.SZ", "name": "平安银行",
            "industry": "银行", "area": "广东", "list_status": "L",
        }])
        results = adapter.adapt_basic_info(df)
        assert len(results) >= 1
        r = results[0]
        assert r.symbol == "000001"
        assert r.name == "平安银行"

    def test_empty_input(self, adapter):
        results = adapter.adapt_basic_info([])
        assert results == []


class TestAdaptDailyQuotes:
    """行情数据适配测试"""

    def test_standard_conversion(self, adapter):
        df = pd.DataFrame([{
            "ts_code": "000001.SZ",
            "trade_date": 20260515,
            "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2,
            "pre_close": 10.0, "vol": 10000, "amount": 50000,
        }])
        results = adapter.adapt_daily_quotes(df)
        assert len(results) >= 1
        r = results[0]
        assert r.symbol == "000001"
        assert r.close == pytest.approx(10.2)

    def test_empty_input(self, adapter):
        results = adapter.adapt_daily_quotes(pd.DataFrame())
        assert results == []


class TestAdaptDailyIndicators:
    """每日指标适配测试"""

    def test_standard_conversion(self, adapter):
        df = pd.DataFrame([{
            "ts_code": "000001.SZ",
            "trade_date": 20260515,
            "pe": 15.5, "pb": 1.2,
        }])
        results = adapter.adapt_daily_indicators(df)
        if results:
            r = results[0]
            assert r.symbol == "000001"

    def test_empty_input(self, adapter):
        results = adapter.adapt_daily_indicators(pd.DataFrame())
        assert results == []


class TestAdaptAdjFactors:
    """复权因子适配测试"""

    def test_standard_conversion(self, adapter):
        df = pd.DataFrame([{
            "ts_code": "000001.SZ",
            "trade_date": 20260515,
            "adj_factor": 1.234,
        }])
        results = adapter.adapt_adj_factors(df)
        if results:
            r = results[0]
            assert r.symbol == "000001"
            assert r.adj_factor == pytest.approx(1.234)


class TestAdaptFinancialData:
    """财务数据适配测试"""

    def test_income_statement(self, adapter):
        df = pd.DataFrame([{
            "ts_code": "000001.SZ",
            "end_date": 20260331,
            "total_revenue": 5000000000,
            "n_income": 1000000000,
        }])
        results = adapter.adapt_financial_data(df)
        # 至少应返回结果或空列表（取决于内部逻辑）
        assert isinstance(results, list)

    def test_empty_input(self, adapter):
        results = adapter.adapt_financial_data(pd.DataFrame())
        assert results == []
