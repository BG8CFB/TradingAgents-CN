"""TushareAdapter 各域 adapt_* 方法单元测试"""

import pandas as pd
import pytest

from app.data.sources.cn.tushare.adapter import TushareAdapter


@pytest.fixture
def adapter():
    return TushareAdapter(provider=None)


class TestAdaptBasicInfo:
    """基础信息适配测试"""

    def test_ts_code_parsing(self, adapter):
        row = {"ts_code": "000001.SZ", "name": "平安银行", "industry": "银行", "area": "广东"}
        result = adapter.adapt_basic_info(row)

        assert result.symbol == "000001"
        assert result.name == "平安银行"
        assert result.exchange == "SZSE"
        assert result.data_source == "tushare"

    def test_market_value_conversion(self, adapter):
        """市值: 万元 → 亿元 (÷ 10000)"""
        row = {"ts_code": "600036.SH", "name": "招商银行", "total_mv": 100000, "circ_mv": 80000}
        result = adapter.adapt_basic_info(row)

        assert result.total_mv == pytest.approx(10.0)
        assert result.circ_mv == pytest.approx(8.0)


class TestAdaptDailyQuote:
    """行情数据适配测试"""

    def test_volume_conversion(self, adapter):
        """成交量: 手 → 股 (× 100)"""
        row = {
            "ts_code": "000001.SZ",
            "trade_date": "20260515",
            "open": 10.0,
            "high": 10.5,
            "low": 9.8,
            "close": 10.2,
            "pre_close": 10.0,
            "vol": 10000,
            "amount": 50000,
        }
        result = adapter.adapt_daily_quote(row)

        assert result.symbol == "000001"
        assert result.volume == pytest.approx(1000000)  # 10000 手 × 100
        assert result.amount == pytest.approx(50000000)  # 50000 千元 × 1000
        assert result.trade_date == "2026-05-15"

    def test_change_calculation(self, adapter):
        """涨跌自动计算"""
        row = {
            "ts_code": "000001.SZ",
            "trade_date": "20260515",
            "close": 10.5,
            "pre_close": 10.0,
            "vol": 1000,
        }
        result = adapter.adapt_daily_quote(row)

        assert result.change == pytest.approx(0.5)
        assert result.pct_chg == pytest.approx(5.0)


class TestAdaptDailyIndicators:
    """每日指标适配测试"""

    def test_standard_conversion(self, adapter):
        row = {
            "ts_code": "000001.SZ",
            "trade_date": "20260515",
            "pe": 15.5,
            "pb": 1.2,
            "ps": 3.0,
            "turnover_rate": 2.5,
            "turnover_rate_f": 3.0,
            "total_mv": 500000,
            "circ_mv": 400000,
            "volume_ratio": 1.1,
        }
        result = adapter.adapt_daily_indicators(row)

        assert result is not None
        assert result.symbol == "000001"
        assert result.pe_ttm == pytest.approx(15.5)
        assert result.trade_date == "2026-05-15"
        # 市值: 万元 → 元 (× 10000)
        assert result.total_mv == pytest.approx(500000 * 10000)
        assert result.circ_mv == pytest.approx(400000 * 10000)

    def test_skip_empty_trade_date(self, adapter):
        row = {"ts_code": "000001.SZ", "trade_date": None}
        result = adapter.adapt_daily_indicators(row)
        assert result is None


class TestAdaptAdjFactors:
    """复权因子适配测试"""

    def test_standard_conversion(self, adapter):
        row = {
            "ts_code": "000001.SZ",
            "trade_date": "20260515",
            "adj_factor": 1.234,
        }
        result = adapter.adapt_adj_factors(row)

        assert result is not None
        assert result.symbol == "000001"
        assert result.adj_factor == pytest.approx(1.234)
        assert result.trade_date == "2026-05-15"

    def test_skip_empty_trade_date(self, adapter):
        row = {"ts_code": "000001.SZ", "trade_date": None}
        result = adapter.adapt_adj_factors(row)
        assert result is None


class TestAdaptFinancial:
    """财务数据适配测试"""

    def test_income_statement_detection(self, adapter):
        row = {
            "ts_code": "000001.SZ",
            "end_date": "20260331",
            "total_revenue": 5000000000,
            "n_income": 1000000000,
            "total_assets": 100000000000,
            "total_hldr_eqy_exc_min_int": 80000000000,
        }
        result = adapter.adapt_financial(row)

        assert result is not None
        assert result.symbol == "000001"
        assert result.report_period == "2026-03-31"
        assert result.statement_type == "income"
        assert result.revenue == pytest.approx(5e9)
        assert result.net_profit == pytest.approx(1e9)

    def test_balance_sheet_detection(self, adapter):
        row = {
            "ts_code": "000001.SZ",
            "end_date": "20260331",
            "total_assets": 100000000000,
            "total_cur_assets": 50000000000,
            "total_liab": 20000000000,
            "total_hldr_eqy_exc_min_int": 80000000000,
        }
        result = adapter.adapt_financial(row)

        assert result is not None
        assert result.statement_type == "balance"

    def test_indicator_detection(self, adapter):
        row = {
            "ts_code": "000001.SZ",
            "end_date": "20260331",
            "roe": 12.5,
            "eps": 0.5,
            "bps": 8.0,
            "grossprofit_margin": 40.0,
        }
        result = adapter.adapt_financial(row)

        assert result is not None
        assert result.statement_type == "indicator"
        assert result.roe == pytest.approx(12.5)

    def test_extra_data_collection(self, adapter):
        row = {
            "ts_code": "000001.SZ",
            "end_date": "20260331",
            "roe": 12.5,
            "custom_field_1": "value1",
            "custom_field_2": 42,
        }
        result = adapter.adapt_financial(row)

        assert result is not None
        assert result.extra_data is not None
        assert "custom_field_1" in result.extra_data
        assert result.extra_data["custom_field_1"] == "value1"
