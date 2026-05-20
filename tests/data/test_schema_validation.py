"""Schema 验证测试"""

from app.data.schema.stock_daily_indicators import DailyIndicatorsSchema
from app.data.schema.stock_adj_factors import AdjFactorsSchema
from app.data.schema.trade_calendar import TradeCalendarSchema
from app.data.schema.sync_metadata import SyncCheckpointSchema, SyncEventSchema, SourceHealthSchema
from app.data.schema.stock_financial_data import FinancialDataSchema
from app.data.schema.collections import get_collection_name, get_all_collections_for_market


class TestDailyIndicatorsSchema:
    def test_from_raw(self):
        raw = {"symbol": "000001", "trade_date": "2026-05-19", "pe_ttm": 12.5, "pb": 1.3}
        schema = DailyIndicatorsSchema.from_raw(raw, "tushare")
        assert schema.symbol == "000001"
        assert schema.trade_date == "2026-05-19"
        assert schema.pe_ttm == 12.5
        assert schema.data_source == "tushare"

    def test_to_db_doc_filters_none(self):
        schema = DailyIndicatorsSchema(symbol="000001", trade_date="2026-05-19", data_source="tushare", updated_at="2026-05-19T00:00:00")
        doc = schema.to_db_doc()
        assert "pe_ttm" not in doc  # None 值应被过滤
        assert doc["symbol"] == "000001"


class TestAdjFactorsSchema:
    def test_from_raw(self):
        raw = {"symbol": "600036", "trade_date": "2026-05-19", "adj_factor": 25.3}
        schema = AdjFactorsSchema.from_raw(raw, "tushare")
        assert schema.symbol == "600036"
        assert schema.adj_factor == 25.3

    def test_missing_optional_fields(self):
        schema = AdjFactorsSchema(symbol="000001", trade_date="2026-05-19", data_source="akshare", updated_at="")
        doc = schema.to_db_doc()
        assert schema.fore_adj_factor is None
        assert schema.back_adj_factor is None


class TestTradeCalendarSchema:
    def test_from_raw(self):
        raw = {"exchange": "SSE", "cal_date": "2026-05-19", "is_open": True, "pretrade_date": "2026-05-16"}
        schema = TradeCalendarSchema.from_raw(raw, "tushare")
        assert schema.exchange == "SSE"
        assert schema.is_open is True
        assert schema.pretrade_date == "2026-05-16"


class TestSyncMetadataSchema:
    def test_checkpoint_from_raw(self):
        raw = {"domain": "daily_quotes", "source": "tushare", "last_sync_date": "2026-05-19", "status": "success"}
        schema = SyncCheckpointSchema.from_raw(raw, "tushare")
        assert schema.domain == "daily_quotes"
        assert schema.status == "success"

    def test_event_from_raw(self):
        raw = {"event_type": "SOURCE_FALLBACK", "domain": "daily_quotes", "source": "akshare",
               "fallback_from": "tushare", "fallback_to": "akshare", "fallback_reason": "timeout"}
        schema = SyncEventSchema.from_raw(raw, "akshare")
        assert schema.event_type == "SOURCE_FALLBACK"
        assert schema.fallback_from == "tushare"

    def test_source_health_from_raw(self):
        raw = {"source": "tushare", "domain": "daily_quotes", "circuit_state": "closed", "success_rate_1h": 0.95}
        schema = SourceHealthSchema.from_raw(raw, "tushare")
        assert schema.circuit_state == "closed"
        assert schema.success_rate_1h == 0.95


class TestFinancialDataSchema:
    def test_statement_type_default(self):
        schema = FinancialDataSchema(symbol="000001", report_period="2026-03-31", data_source="tushare", updated_at="")
        assert schema.statement_type == "indicator"

    def test_extra_data(self):
        schema = FinancialDataSchema(
            symbol="000001", report_period="2026-03-31",
            statement_type="income", data_source="tushare", updated_at="",
            extra_data={"operating_cost": 100000, "selling_expense": 20000},
        )
        doc = schema.to_db_doc()
        assert doc["extra_data"]["operating_cost"] == 100000

    def test_backward_compatible_raw_data(self):
        schema = FinancialDataSchema(
            symbol="000001", data_source="tushare", updated_at="",
            raw_data={"some_old_field": "value"},
        )
        doc = schema.to_db_doc()
        assert doc["raw_data"]["some_old_field"] == "value"


class TestCollectionsMap:
    def test_cn_collections_count(self):
        cn = get_all_collections_for_market("CN")
        assert len(cn) == 11

    def test_new_collections_present(self):
        assert get_collection_name("CN", "daily_indicators") == "stock_daily_indicators"
        assert get_collection_name("CN", "adj_factors") == "stock_adj_factors"
        assert get_collection_name("CN", "trade_calendar") == "trade_calendar"
        assert get_collection_name("CN", "sync_checkpoints") == "sync_checkpoints"
        assert get_collection_name("CN", "sync_events") == "sync_events"
        assert get_collection_name("CN", "source_health") == "source_health"

    def test_hk_suffix(self):
        assert get_collection_name("HK", "daily_indicators") == "stock_daily_indicators_hk"
        assert get_collection_name("HK", "adj_factors") == "stock_adj_factors_hk"

    def test_us_suffix(self):
        assert get_collection_name("US", "daily_indicators") == "stock_daily_indicators_us"

    def test_existing_collections_unchanged(self):
        assert get_collection_name("CN", "basic_info") == "stock_basic_info"
        assert get_collection_name("CN", "daily_quotes") == "stock_daily_quotes"
        assert get_collection_name("HK", "basic_info") == "stock_basic_info_hk"

    def test_invalid_market_raises(self):
        import pytest
        with pytest.raises(KeyError):
            get_collection_name("XX", "basic_info")

    def test_invalid_data_type_raises(self):
        import pytest
        with pytest.raises(KeyError):
            get_collection_name("CN", "nonexistent")
