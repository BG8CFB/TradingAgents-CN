"""后处理器测试 — PeriodAggregator (日→周/月) 与 AdjFactorCalculator (复权因子)。"""

import pytest

from app.data.processor.post_processors.period_aggregator import PeriodAggregator
from app.data.processor.post_processors.adj_factor_calculator import AdjFactorCalculator


# ── PeriodAggregator 测试 ─────────────────────────────────


class TestPeriodAggregatorWeekly:
    """日线 → 周线聚合。"""

    def setup_method(self):
        self.agg = PeriodAggregator()

    def test_empty_input(self):
        assert self.agg.aggregate_to_weekly([]) == []

    def test_single_record(self):
        records = [
            {"symbol": "000001", "trade_date": "2024-01-15", "open": 10.0,
             "high": 11.0, "low": 9.5, "close": 10.5, "volume": 1000,
             "amount": 10500, "pre_close": 9.8},
        ]
        result = self.agg.aggregate_to_weekly(records)
        assert len(result) == 1
        assert result[0]["period"] == "weekly"
        assert result[0]["close"] == 10.5
        assert result[0]["open"] == 10.0
        assert result[0]["volume"] == 1000

    def test_multi_day_same_week(self):
        records = [
            {"symbol": "000001", "trade_date": "2024-01-15", "open": 10.0,
             "high": 11.0, "low": 9.5, "close": 10.5, "volume": 1000,
             "amount": 10500, "pre_close": 9.8},
            {"symbol": "000001", "trade_date": "2024-01-16", "open": 10.5,
             "high": 12.0, "low": 10.0, "close": 11.5, "volume": 2000,
             "amount": 23000, "pre_close": 10.5},
            {"symbol": "000001", "trade_date": "2024-01-17", "open": 11.5,
             "high": 13.0, "low": 11.0, "close": 12.0, "volume": 1500,
             "amount": 18000, "pre_close": 11.5},
        ]
        result = self.agg.aggregate_to_weekly(records)
        assert len(result) == 1
        w = result[0]
        assert w["open"] == 10.0       # 第一天 open
        assert w["close"] == 12.0      # 最后一天 close
        assert w["high"] == 13.0       # 最高
        assert w["low"] == 9.5         # 最低
        assert w["volume"] == 4500     # 总量
        assert w["amount"] == 51500    # 总额
        assert w["pre_close"] == 9.8   # 第一天 pre_close
        assert w["period"] == "weekly"

    def test_change_and_pct_chg_computed(self):
        records = [
            {"symbol": "000001", "trade_date": "2024-01-15", "open": 10.0,
             "high": 11.0, "low": 9.5, "close": 10.5, "volume": 1000,
             "amount": 10500, "pre_close": 10.0},
        ]
        result = self.agg.aggregate_to_weekly(records)
        assert result[0]["change"] == 0.5
        assert abs(result[0]["pct_chg"] - 5.0) < 0.01

    def test_cross_week_split(self):
        records = [
            {"symbol": "000001", "trade_date": "2024-01-12", "open": 10.0,
             "high": 11.0, "low": 9.5, "close": 10.5, "volume": 1000,
             "amount": 10500, "pre_close": 10.0},
            {"symbol": "000001", "trade_date": "2024-01-15", "open": 10.5,
             "high": 12.0, "low": 10.0, "close": 11.0, "volume": 2000,
             "amount": 22000, "pre_close": 10.5},
        ]
        result = self.agg.aggregate_to_weekly(records)
        assert len(result) == 2  # 分属不同 ISO 周

    def test_multiple_symbols_separated(self):
        records = [
            {"symbol": "000001", "trade_date": "2024-01-15", "open": 10.0,
             "high": 11.0, "low": 9.5, "close": 10.5, "volume": 1000,
             "amount": 10500, "pre_close": 10.0},
            {"symbol": "600036", "trade_date": "2024-01-15", "open": 30.0,
             "high": 31.0, "low": 29.0, "close": 30.5, "volume": 500,
             "amount": 15250, "pre_close": 30.0},
        ]
        result = self.agg.aggregate_to_weekly(records)
        assert len(result) == 2
        symbols = {r["symbol"] for r in result}
        assert symbols == {"000001", "600036"}

    def test_records_without_trade_date_skipped(self):
        records = [
            {"symbol": "000001", "open": 10.0},
            {"symbol": "000001", "trade_date": "2024-01-15", "open": 10.0,
             "high": 11.0, "low": 9.5, "close": 10.5, "volume": 1000,
             "amount": 10500, "pre_close": 10.0},
        ]
        result = self.agg.aggregate_to_weekly(records)
        assert len(result) == 1

    def test_records_without_symbol_skipped(self):
        records = [
            {"trade_date": "2024-01-15", "open": 10.0},
            {"symbol": "000001", "trade_date": "2024-01-15", "open": 10.0,
             "high": 11.0, "low": 9.5, "close": 10.5, "volume": 1000,
             "amount": 10500, "pre_close": 10.0},
        ]
        result = self.agg.aggregate_to_weekly(records)
        assert len(result) == 1

    def test_none_volume_amount_treated_as_zero(self):
        records = [
            {"symbol": "000001", "trade_date": "2024-01-15", "open": 10.0,
             "high": 11.0, "low": 9.5, "close": 10.5, "volume": None,
             "amount": None, "pre_close": 10.0},
        ]
        result = self.agg.aggregate_to_weekly(records)
        assert len(result) == 1
        assert result[0]["volume"] == 0
        assert result[0]["amount"] == 0

    def test_all_low_none_returns_none(self):
        """当所有 low 值为 None 时，聚合结果中的 low 应为 None。"""
        records = [
            {"symbol": "000001", "trade_date": "2024-01-15", "open": 10.0,
             "high": None, "low": None, "close": 10.5, "volume": 100,
             "amount": 10500, "pre_close": 10.0},
        ]
        result = self.agg.aggregate_to_weekly(records)
        assert len(result) == 1
        assert result[0]["low"] is None
        assert result[0]["high"] is None


class TestPeriodAggregatorMonthly:
    """日线 → 月线聚合。"""

    def setup_method(self):
        self.agg = PeriodAggregator()

    def test_empty_input(self):
        assert self.agg.aggregate_to_monthly([]) == []

    def test_same_month_merged(self):
        records = [
            {"symbol": "000001", "trade_date": "2024-01-05", "open": 10.0,
             "high": 11.0, "low": 9.5, "close": 10.5, "volume": 1000,
             "amount": 10500, "pre_close": 10.0},
            {"symbol": "000001", "trade_date": "2024-01-20", "open": 10.5,
             "high": 12.0, "low": 10.0, "close": 11.5, "volume": 2000,
             "amount": 23000, "pre_close": 10.5},
        ]
        result = self.agg.aggregate_to_monthly(records)
        assert len(result) == 1
        m = result[0]
        assert m["period"] == "monthly"
        assert m["open"] == 10.0
        assert m["close"] == 11.5
        assert m["volume"] == 3000

    def test_different_months_separated(self):
        records = [
            {"symbol": "000001", "trade_date": "2024-01-31", "open": 10.0,
             "high": 11.0, "low": 9.5, "close": 10.5, "volume": 1000,
             "amount": 10500, "pre_close": 10.0},
            {"symbol": "000001", "trade_date": "2024-02-02", "open": 10.5,
             "high": 12.0, "low": 10.0, "close": 11.0, "volume": 800,
             "amount": 8800, "pre_close": 10.5},
        ]
        result = self.agg.aggregate_to_monthly(records)
        assert len(result) == 2

    def test_month_key_extraction(self):
        assert PeriodAggregator._month_key("2024-03-15") == "2024-03"

    def test_week_key_iso_format(self):
        key = PeriodAggregator._week_key("2024-01-15")
        assert key.startswith("2024-W")


# ── AdjFactorCalculator 测试 ──────────────────────────────


class TestAdjFactorCalculator:
    """从公司行为推导复权因子。"""

    def setup_method(self):
        self.calc = AdjFactorCalculator()

    def test_empty_actions(self):
        assert self.calc.calculate_from_corporate_actions([]) == []

    def test_cash_dividend_reduces_factor(self):
        actions = [
            {"symbol": "AAPL", "ex_date": "2024-03-15", "action_type": "cash_dividend",
             "amount": 0.5, "market": "US", "updated_at": "2024-03-15"},
        ]
        result = self.calc.calculate_from_corporate_actions(actions)
        assert len(result) == 1
        assert result[0]["adj_factor"] < 1.0
        assert result[0]["symbol"] == "AAPL"
        assert result[0]["trade_date"] == "2024-03-15"
        assert result[0]["data_source"] == "local_derived"

    def test_special_dividend_reduces_factor(self):
        actions = [
            {"symbol": "AAPL", "ex_date": "2024-06-01", "action_type": "special_dividend",
             "amount": 2.0, "market": "US", "updated_at": "2024-06-01"},
        ]
        result = self.calc.calculate_from_corporate_actions(actions)
        assert len(result) == 1
        assert result[0]["adj_factor"] < 1.0

    def test_stock_split_adjusts_factor(self):
        actions = [
            {"symbol": "AAPL", "ex_date": "2024-08-01", "action_type": "stock_split",
             "ratio_from": 1, "ratio_to": 4, "market": "US", "updated_at": "2024-08-01"},
        ]
        result = self.calc.calculate_from_corporate_actions(actions)
        assert result[0]["adj_factor"] == 4.0

    def test_reverse_split_adjusts_factor(self):
        actions = [
            {"symbol": "TSLA", "ex_date": "2024-09-01", "action_type": "reverse_split",
             "ratio_from": 5, "ratio_to": 1, "market": "US", "updated_at": "2024-09-01"},
        ]
        result = self.calc.calculate_from_corporate_actions(actions)
        assert result[0]["adj_factor"] == 0.2

    def test_bonus_issue_adjusts_factor(self):
        actions = [
            {"symbol": "0700", "ex_date": "2024-05-01", "action_type": "bonus_issue",
             "ratio_from": 10, "ratio_to": 1, "market": "HK", "updated_at": "2024-05-01"},
        ]
        result = self.calc.calculate_from_corporate_actions(actions)
        assert result[0]["adj_factor"] == round(1 / 11, 6)

    def test_rights_issue_adjusts_factor(self):
        actions = [
            {"symbol": "0700", "ex_date": "2024-07-01", "action_type": "rights_issue",
             "ratio_from": 10, "ratio_to": 1, "rights_price": 50.0,
             "market": "HK", "updated_at": "2024-07-01"},
        ]
        result = self.calc.calculate_from_corporate_actions(actions)
        assert len(result) == 1
        assert result[0]["adj_factor"] != 1.0

    def test_multiple_actions_cumulative(self):
        actions = [
            {"symbol": "AAPL", "ex_date": "2024-03-15", "action_type": "stock_split",
             "ratio_from": 1, "ratio_to": 2, "market": "US", "updated_at": "2024-03-15"},
            {"symbol": "AAPL", "ex_date": "2024-06-15", "action_type": "stock_split",
             "ratio_from": 1, "ratio_to": 3, "market": "US", "updated_at": "2024-06-15"},
        ]
        result = self.calc.calculate_from_corporate_actions(actions)
        assert len(result) == 2
        assert result[0]["adj_factor"] == 2.0
        assert result[1]["adj_factor"] == 6.0

    def test_custom_base_factor(self):
        actions = [
            {"symbol": "AAPL", "ex_date": "2024-03-15", "action_type": "stock_split",
             "ratio_from": 1, "ratio_to": 2, "market": "US", "updated_at": "2024-03-15"},
        ]
        result = self.calc.calculate_from_corporate_actions(actions, base_factor=0.5)
        assert result[0]["adj_factor"] == 1.0

    def test_zero_amount_skipped(self):
        actions = [
            {"symbol": "AAPL", "ex_date": "2024-03-15", "action_type": "cash_dividend",
             "amount": 0, "market": "US", "updated_at": "2024-03-15"},
        ]
        result = self.calc.calculate_from_corporate_actions(actions)
        assert result[0]["adj_factor"] == 1.0

    def test_none_amount_treated_as_zero(self):
        actions = [
            {"symbol": "AAPL", "ex_date": "2024-03-15", "action_type": "cash_dividend",
             "amount": None, "market": "US", "updated_at": "2024-03-15"},
        ]
        result = self.calc.calculate_from_corporate_actions(actions)
        assert result[0]["adj_factor"] == 1.0

    def test_zero_ratio_from_falls_back_to_one(self):
        """ratio_from=0 时 `or 1` 回退为 1，factor *= ratio_to/1 = 4.0。"""
        actions = [
            {"symbol": "AAPL", "ex_date": "2024-03-15", "action_type": "stock_split",
             "ratio_from": 0, "ratio_to": 4, "market": "US", "updated_at": "2024-03-15"},
        ]
        result = self.calc.calculate_from_corporate_actions(actions)
        assert result[0]["adj_factor"] == 4.0

    def test_unknown_action_type_no_effect(self):
        actions = [
            {"symbol": "AAPL", "ex_date": "2024-03-15", "action_type": "merger",
             "market": "US", "updated_at": "2024-03-15"},
        ]
        result = self.calc.calculate_from_corporate_actions(actions)
        assert result[0]["adj_factor"] == 1.0

    def test_output_fields_complete(self):
        actions = [
            {"symbol": "AAPL", "ex_date": "2024-03-15", "action_type": "stock_split",
             "ratio_from": 1, "ratio_to": 2, "market": "US", "updated_at": "2024-03-15"},
        ]
        result = self.calc.calculate_from_corporate_actions(actions)
        rec = result[0]
        assert "symbol" in rec
        assert "trade_date" in rec
        assert "adj_factor" in rec
        assert "fore_adj_factor" in rec
        assert "market" in rec
        assert "data_source" in rec
        assert "updated_at" in rec

    def test_fore_adj_factor_equals_adj_factor(self):
        actions = [
            {"symbol": "AAPL", "ex_date": "2024-03-15", "action_type": "cash_dividend",
             "amount": 0.5, "market": "US", "updated_at": "2024-03-15"},
        ]
        result = self.calc.calculate_from_corporate_actions(actions)
        assert result[0]["fore_adj_factor"] == result[0]["adj_factor"]

    def test_default_market_is_us(self):
        actions = [
            {"symbol": "AAPL", "ex_date": "2024-03-15", "action_type": "stock_split",
             "ratio_from": 1, "ratio_to": 2, "updated_at": "2024-03-15"},
        ]
        result = self.calc.calculate_from_corporate_actions(actions)
        assert result[0]["market"] == "US"

    def test_adj_factor_rounded_to_6_decimals(self):
        actions = [
            {"symbol": "AAPL", "ex_date": "2024-03-15", "action_type": "reverse_split",
             "ratio_from": 3, "ratio_to": 1, "market": "US", "updated_at": "2024-03-15"},
        ]
        result = self.calc.calculate_from_corporate_actions(actions)
        factor_str = str(result[0]["adj_factor"])
        decimal_places = len(factor_str.split(".")[-1])
        assert decimal_places <= 6
