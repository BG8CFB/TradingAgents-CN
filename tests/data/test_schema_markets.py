"""测试 schema/markets 三市场特化字段。"""

import pytest
from dataclasses import fields


class TestCNBasicInfoFields:
    def test_cn_fields(self):
        from app.data.schema.markets.cn import CNBasicInfoFields
        f = CNBasicInfoFields(area="广东", market_board="主板")
        assert f.area == "广东"
        assert f.market_board == "主板"


class TestHKFields:
    def test_hk_basic_info_fields(self):
        from app.data.schema.markets.hk import HKBasicInfoFields
        f = HKBasicInfoFields(connect_status="Y", dual_listed=True)
        assert f.connect_status == "Y"
        assert f.dual_listed is True

    def test_hk_corporate_actions_fields(self):
        from app.data.schema.markets.hk import HKCorporateActionsFields
        f = HKCorporateActionsFields(amount_hkd=1000.0)
        assert f.amount_hkd == 1000.0

    def test_hk_market_quotes_fields(self):
        from app.data.schema.markets.hk import HKMarketQuotesFields
        f = HKMarketQuotesFields(quote_source_type="realtime", session="AM")
        assert f.quote_source_type == "realtime"


class TestUSFields:
    def test_us_basic_info_fields(self):
        from app.data.schema.markets.us import USBasicInfoFields
        f = USBasicInfoFields(sector="Technology", market_cap_tier="Mega", is_adr=False, cik="12345")
        assert f.sector == "Technology"
        assert f.is_adr is False

    def test_us_daily_quotes_fields(self):
        from app.data.schema.markets.us import USDailyQuotesFields
        f = USDailyQuotesFields(adj_close=150.5)
        assert f.adj_close == 150.5

    def test_us_market_quotes_fields(self):
        from app.data.schema.markets.us import USMarketQuotesFields
        f = USMarketQuotesFields(pre_market_price=148.0, post_market_price=151.0)
        assert f.pre_market_price == 148.0
        assert f.post_market_price == 151.0
