"""validation.py 写入前校验测试"""

from app.data.processor.validation import DataValidator


class TestDataValidator:
    def setup_method(self):
        self.validator = DataValidator()

    def test_valid_daily_quotes(self):
        record = {"symbol": "000001", "trade_date": "2026-05-19", "close": 10.5, "volume": 1000}
        errors = self.validator.validate("daily_quotes", record)
        assert errors == []

    def test_missing_required_field(self):
        record = {"trade_date": "2026-05-19", "close": 10.5}
        errors = self.validator.validate("daily_quotes", record)
        assert len(errors) > 0
        assert any(e.field == "symbol" for e in errors)

    def test_negative_price(self):
        record = {"symbol": "000001", "trade_date": "2026-05-19", "close": -1.0}
        errors = self.validator.validate("daily_quotes", record)
        assert any(e.field == "close" for e in errors)

    def test_pct_chg_out_of_range(self):
        record = {"symbol": "000001", "trade_date": "2026-05-19", "pct_chg": 50.0}
        errors = self.validator.validate("daily_quotes", record)
        assert any(e.field == "pct_chg" for e in errors)

    def test_pct_chg_in_range(self):
        record = {"symbol": "000001", "trade_date": "2026-05-19", "pct_chg": 10.0}
        errors = self.validator.validate("daily_quotes", record)
        assert not any(e.field == "pct_chg" for e in errors)

    def test_invalid_date_format(self):
        record = {"symbol": "000001", "trade_date": "not-a-date"}
        errors = self.validator.validate("daily_quotes", record)
        assert any(e.field == "trade_date" for e in errors)

    def test_valid_date_yyyymmdd(self):
        record = {"symbol": "000001", "trade_date": "20260519"}
        errors = self.validator.validate("daily_quotes", record)
        assert not any(e.field == "trade_date" for e in errors)

    def test_nan_required_field(self):
        record = {"symbol": "NaN", "trade_date": "2026-05-19"}
        errors = self.validator.validate("daily_quotes", record)
        assert any(e.field == "symbol" for e in errors)

    def test_batch_validation(self):
        records = [
            {"symbol": "000001", "trade_date": "2026-05-19"},
            {"symbol": "", "trade_date": "2026-05-19"},  # invalid
            {"symbol": "600036", "trade_date": "2026-05-19"},
        ]
        valid, invalid, errors = self.validator.validate_batch("daily_quotes", records)
        assert len(valid) == 2
        assert len(invalid) == 1

    def test_financial_requires_statement_type(self):
        record = {"symbol": "000001", "report_period": "2026-03-31"}
        errors = self.validator.validate("financial", record)
        assert any(e.field == "statement_type" for e in errors)

    def test_financial_with_statement_type(self):
        record = {"symbol": "000001", "report_period": "2026-03-31", "statement_type": "income"}
        errors = self.validator.validate("financial", record)
        assert not any(e.rule == "required" for e in errors)
