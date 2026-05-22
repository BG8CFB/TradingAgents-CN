"""Schema 验证测试 — 匹配新架构 schema。"""

import pytest

from app.data.schema.domains.daily_indicators import DailyIndicatorsSchema
from app.data.schema.domains.adj_factors import AdjFactorsSchema
from app.data.schema.domains.trade_calendar import TradeCalendarSchema
from app.data.schema.domains.metadata import (
    SyncCheckpointSchema,
    SyncEventSchema,
    SourceHealthSchema,
)
from app.data.schema.domains.financial_data import FinancialDataSchema
from app.data.storage.mongo.collections import (
    get_collection_name,
    get_all_collections,
)


class TestDailyIndicatorsSchema:
    def test_construct_and_to_db_doc(self):
        schema = DailyIndicatorsSchema(
            symbol="000001", market="CN", data_source="tushare",
            trade_date="2026-05-19", pe_ttm=12.5, pb=1.3,
        )
        doc = schema.to_db_doc()
        assert doc["symbol"] == "000001"
        assert doc["trade_date"] == "2026-05-19"
        assert doc["pe_ttm"] == 12.5
        assert doc["data_source"] == "tushare"

    def test_to_db_doc_filters_none(self):
        schema = DailyIndicatorsSchema(
            symbol="000001", market="CN", data_source="tushare",
            trade_date="2026-05-19",
        )
        doc = schema.to_db_doc()
        assert "pe_ttm" not in doc
        assert doc["symbol"] == "000001"
        # updated_at 自动填充
        assert "updated_at" in doc


class TestAdjFactorsSchema:
    def test_construct(self):
        schema = AdjFactorsSchema(
            symbol="600036", market="CN", data_source="tushare",
            trade_date="2026-05-19", adj_factor=25.3,
        )
        assert schema.symbol == "600036"
        assert schema.adj_factor == 25.3

    def test_missing_optional_fields(self):
        schema = AdjFactorsSchema(
            symbol="000001", market="CN", data_source="akshare",
            trade_date="2026-05-19",
        )
        doc = schema.to_db_doc()
        assert "fore_adj_factor" not in doc
        assert "back_adj_factor" not in doc


class TestTradeCalendarSchema:
    def test_construct(self):
        schema = TradeCalendarSchema(
            symbol="SSE", market="CN", data_source="tushare",
            exchange="SSE", cal_date="2026-05-19", is_open=True, pretrade_date="2026-05-16",
        )
        assert schema.exchange == "SSE"
        assert schema.is_open is True
        assert schema.pretrade_date == "2026-05-16"


class TestSyncMetadataSchema:
    def test_checkpoint(self):
        schema = SyncCheckpointSchema(
            market="CN", domain="daily_quotes", source="tushare",
            last_sync_date="2026-05-19", status="success",
        )
        doc = schema.to_db_doc()
        assert doc["domain"] == "daily_quotes"
        assert doc["status"] == "success"

    def test_event(self):
        schema = SyncEventSchema(
            market="CN", event_type="SOURCE_FALLBACK",
            domain="daily_quotes", source_from="tushare", source_to="akshare",
            reason="timeout",
        )
        doc = schema.to_db_doc()
        assert doc["event_type"] == "SOURCE_FALLBACK"
        assert doc["source_from"] == "tushare"

    def test_source_health(self):
        schema = SourceHealthSchema(
            market="CN", source="tushare", domain="daily_quotes",
            circuit_state="closed", success_rate_1h=0.95,
        )
        assert schema.circuit_state == "closed"
        assert schema.success_rate_1h == 0.95


class TestFinancialDataSchema:
    def test_default_statement_type_none(self):
        schema = FinancialDataSchema(
            symbol="000001", market="CN", data_source="tushare",
            report_period="2026-03-31",
        )
        assert schema.statement_type is None

    def test_to_db_doc(self):
        schema = FinancialDataSchema(
            symbol="000001", market="CN", data_source="tushare",
            report_period="2026-03-31", statement_type="income",
            revenue=100000.0, net_profit=20000.0,
        )
        doc = schema.to_db_doc()
        assert doc["revenue"] == 100000.0
        assert doc["net_profit"] == 20000.0


class TestCollectionsMap:
    def test_cn_collections_count(self):
        cn = get_all_collections("CN")
        assert len(cn) >= 9  # 至少 9 个业务集合 + 4 个元数据集合

    def test_new_collections_present(self):
        assert get_collection_name("daily_indicators", "CN") == "stock_daily_indicators"
        assert get_collection_name("adj_factors", "CN") == "stock_adj_factors"
        assert get_collection_name("trade_calendar", "CN") == "trade_calendar"
        assert get_collection_name("sync_checkpoints", "CN") == "sync_checkpoints"
        assert get_collection_name("sync_events", "CN") == "sync_events"
        assert get_collection_name("source_health", "CN") == "source_health"

    def test_hk_suffix(self):
        assert get_collection_name("daily_indicators", "HK") == "stock_daily_indicators_hk"
        assert get_collection_name("adj_factors", "HK") == "stock_adj_factors_hk"

    def test_us_suffix(self):
        assert get_collection_name("daily_indicators", "US") == "stock_daily_indicators_us"

    def test_existing_collections_unchanged(self):
        assert get_collection_name("basic_info", "CN") == "stock_basic_info"
        assert get_collection_name("daily_quotes", "CN") == "stock_daily_quotes"
        assert get_collection_name("basic_info", "HK") == "stock_basic_info_hk"

    def test_invalid_market_returns_base_name(self):
        result = get_collection_name("basic_info", "XX")
        assert result == "stock_basic_info"

    def test_invalid_data_type_raises(self):
        with pytest.raises(KeyError):
            get_collection_name("nonexistent", "CN")
