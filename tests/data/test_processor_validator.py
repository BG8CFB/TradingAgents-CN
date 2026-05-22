"""Validator 写入前校验测试 — 覆盖所有域的必填字段、价格范围、涨跌幅。"""

import pytest

from app.data.processor.validator import Validator


class TestValidator:
    def setup_method(self):
        self.validator = Validator()

    def test_valid_basic_info(self):
        records = [
            {"symbol": "000001", "market": "CN", "name": "平安银行"},
            {"symbol": "600000", "market": "CN", "name": "浦发银行"},
        ]
        valid, errors = self.validator.validate(records, "basic_info", "CN")
        assert len(valid) == 2
        assert len(errors) == 0

    def test_missing_symbol_filtered(self):
        records = [
            {"symbol": "000001", "market": "CN", "name": "平安银行"},
            {"market": "CN", "name": "无代码"},
        ]
        valid, errors = self.validator.validate(records, "basic_info", "CN")
        assert len(valid) == 1
        assert len(errors) == 1

    def test_valid_daily_quotes(self):
        records = [{"symbol": "000001", "trade_date": "2026-05-19", "close": 10.5}]
        valid, errors = self.validator.validate(records, "daily_quotes", "CN")
        assert len(valid) == 1
        assert len(errors) == 0

    def test_daily_quotes_requires_trade_date(self):
        records = [
            {"symbol": "000001", "trade_date": "2024-01-15", "close": 10.5},
            {"symbol": "000001", "close": 10.5},
        ]
        valid, errors = self.validator.validate(records, "daily_quotes", "CN")
        assert len(valid) == 1

    def test_missing_required_field(self):
        records = [{"trade_date": "2026-05-19", "close": 10.5}]
        valid, errors = self.validator.validate(records, "daily_quotes", "CN")
        assert len(valid) == 0
        assert len(errors) == 1

    def test_positive_price_validation(self):
        records = [
            {"symbol": "000001", "trade_date": "2024-01-15", "close": 10.5},
            {"symbol": "000001", "trade_date": "2024-01-16", "close": -5.0},
        ]
        valid, errors = self.validator.validate(records, "daily_quotes", "CN")
        assert len(valid) == 1

    def test_negative_price(self):
        records = [{"symbol": "000001", "trade_date": "2026-05-19", "close": -1.0}]
        valid, errors = self.validator.validate(records, "daily_quotes", "CN")
        assert len(valid) == 0
        assert len(errors) == 1

    def test_pct_chg_in_range(self):
        records = [{"symbol": "000001", "trade_date": "2026-05-19", "close": 10.0, "pct_chg": 10.0}]
        valid, errors = self.validator.validate(records, "daily_quotes", "CN")
        assert len(valid) == 1

    def test_pct_chg_out_of_range_cn(self):
        records = [{"symbol": "000001", "trade_date": "2026-05-19", "close": 10.0, "pct_chg": 50.0}]
        valid, errors = self.validator.validate(records, "daily_quotes", "CN")
        assert len(errors) == 1

    def test_batch_validation(self):
        records = [
            {"symbol": "000001", "trade_date": "2026-05-19", "close": 10.0},
            {"trade_date": "2026-05-19", "close": 10.0},
            {"symbol": "600036", "trade_date": "2026-05-19", "close": 15.0},
        ]
        valid, errors = self.validator.validate(records, "daily_quotes", "CN")
        assert len(valid) == 2
        assert len(errors) == 1

    def test_financial_requires_statement_type(self):
        records = [{"symbol": "000001", "report_period": "2026-03-31"}]
        valid, errors = self.validator.validate(records, "financial_data", "CN")
        assert len(errors) == 1

    def test_financial_with_statement_type(self):
        records = [{"symbol": "000001", "report_period": "2026-03-31", "statement_type": "income"}]
        valid, errors = self.validator.validate(records, "financial_data", "CN")
        assert len(valid) == 1

    def test_market_quotes(self):
        records = [{"symbol": "000001", "last_price": 10.0}]
        valid, errors = self.validator.validate(records, "market_quotes", "CN")
        assert len(valid) == 1

    def test_empty_records(self):
        valid, errors = self.validator.validate([], "basic_info", "CN")
        assert valid == []
        assert errors == []

    def test_unknown_domain(self):
        records = [{"symbol": "000001"}]
        valid, errors = self.validator.validate(records, "unknown_domain", "CN")
        assert len(valid) == 1
