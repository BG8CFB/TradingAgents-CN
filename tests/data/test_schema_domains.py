"""测试 schema/domains 各域 Schema 定义。"""

import pytest
from dataclasses import fields


class TestBasicInfoSchema:
    def test_creation(self):
        from app.data.schema.domains.basic_info import StockBasicInfoSchema
        schema = StockBasicInfoSchema(
            symbol="000001", market="CN", data_source="tushare",
            name="平安银行", exchange="SZSE", currency="CNY",
        )
        assert schema.symbol == "000001"
        assert schema.market == "CN"
        assert schema.name == "平安银行"

    def test_to_db_doc(self):
        from app.data.schema.domains.basic_info import StockBasicInfoSchema
        schema = StockBasicInfoSchema(
            symbol="000001", market="CN", data_source="tushare",
        )
        doc = schema.to_db_doc()
        assert "symbol" in doc
        assert "market" in doc
        assert "data_source" in doc
        assert "updated_at" in doc
        # None 值不包含
        assert "name" not in doc
        assert "exchange" not in doc

    def test_all_fields(self):
        from app.data.schema.domains.basic_info import StockBasicInfoSchema
        field_names = {f.name for f in fields(StockBasicInfoSchema)}
        expected = {"symbol", "market", "data_source", "updated_at",
                    "name", "full_symbol", "exchange", "industry",
                    "list_status", "list_date", "delist_date", "currency"}
        assert expected.issubset(field_names)


class TestDailyQuotesSchema:
    def test_creation(self):
        from app.data.schema.domains.daily_quotes import DailyQuotesSchema
        schema = DailyQuotesSchema(
            symbol="000001", market="CN", data_source="tushare",
            trade_date="2024-01-15", open=10.5, close=10.8,
            high=11.0, low=10.3, volume=1000000, amount=10800000,
        )
        assert schema.trade_date == "2024-01-15"
        assert schema.close == 10.8

    def test_to_db_doc_filters_none(self):
        from app.data.schema.domains.daily_quotes import DailyQuotesSchema
        schema = DailyQuotesSchema(
            symbol="000001", market="CN", data_source="tushare",
            trade_date="2024-01-15",
        )
        doc = schema.to_db_doc()
        assert doc["trade_date"] == "2024-01-15"
        assert "open" not in doc


class TestFinancialDataSchema:
    def test_all_fields_present(self):
        from app.data.schema.domains.financial_data import FinancialDataSchema
        field_names = {f.name for f in fields(FinancialDataSchema)}
        expected = {"revenue", "net_profit", "roe", "eps", "report_period",
                    "statement_type", "total_assets", "total_equity"}
        assert expected.issubset(field_names)


class TestCorporateActionsSchema:
    def test_creation(self):
        from app.data.schema.domains.corporate_actions import CorporateActionsSchema
        schema = CorporateActionsSchema(
            symbol="00700", market="HK", data_source="akshare_hk",
            ex_date="2024-05-15", action_type="cash_dividend",
            amount=1.5, currency="HKD",
        )
        assert schema.action_type == "cash_dividend"
        assert schema.amount == 1.5


class TestStockNewsSchema:
    def test_compute_hash(self):
        from app.data.schema.domains.stock_news import StockNewsSchema
        h1 = StockNewsSchema.compute_hash("Title A", "2024-01-01")
        h2 = StockNewsSchema.compute_hash("Title A", "2024-01-01")
        h3 = StockNewsSchema.compute_hash("Title B", "2024-01-01")
        assert h1 == h2
        assert h1 != h3

    def test_hash_in_doc(self):
        from app.data.schema.domains.stock_news import StockNewsSchema
        schema = StockNewsSchema(
            symbol="000001", market="CN", data_source="tushare",
            title="Test", content_hash="abc123",
        )
        doc = schema.to_db_doc()
        assert doc["content_hash"] == "abc123"
