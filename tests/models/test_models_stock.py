"""
股票数据模型单元测试
覆盖 MarketType, ExchangeType, StockStatus, StockBasicInfoExtended,
MarketQuotesExtended, MarketInfo, TechnicalIndicators 等
"""

import pytest
from datetime import datetime, timezone
from pydantic import ValidationError

from app.models.stock_models import (
    MarketInfo,
    TechnicalIndicators,
    StockBasicInfoExtended,
    MarketQuotesExtended,
    StockBasicInfoResponse,
    MarketQuotesResponse,
    StockListResponse,
    to_str_id,
)


# ---------------------------------------------------------------------------
# to_str_id 辅助函数
# ---------------------------------------------------------------------------


class TestToStrId:
    """ObjectId 转字符串辅助函数测试"""

    def test_string_passthrough(self):
        """字符串直接返回"""
        assert to_str_id("test") == "test"

    def test_number_to_string(self):
        """数字转字符串"""
        assert to_str_id(123) == "123"

    def test_exception_returns_empty(self):
        """异常返回空字符串"""
        class Bad:
            def __str__(self):
                raise ValueError("fail")
        assert to_str_id(Bad()) == ""


# ---------------------------------------------------------------------------
# MarketType Literal
# ---------------------------------------------------------------------------


class TestMarketType:
    """市场类型 Literal 测试"""

    def test_valid_values(self):
        """合法市场类型"""
        from app.models.stock_models import MarketType
        # Literal["CN", "HK", "US"] - 直接在模型中验证
        info = MarketInfo(
            market="CN",
            exchange="SZSE",
            exchange_name="深圳证券交易所",
            currency="CNY",
            timezone="Asia/Shanghai",
        )
        assert info.market == "CN"


class TestExchangeType:
    """交易所类型 Literal 测试"""

    def test_all_exchanges(self):
        """所有交易所类型"""
        from app.models.stock_models import ExchangeType
        for exchange in ("SZSE", "SSE", "SEHK", "NYSE", "NASDAQ"):
            info = MarketInfo(
                market="CN",
                exchange=exchange,
                exchange_name="test",
                currency="CNY",
                timezone="Asia/Shanghai",
            )
            assert info.exchange == exchange

    def test_invalid_exchange(self):
        """无效交易所应报错"""
        with pytest.raises(ValidationError):
            MarketInfo(
                market="CN",
                exchange="INVALID",
                exchange_name="test",
                currency="CNY",
                timezone="Asia/Shanghai",
            )


class TestStockStatus:
    """上市状态 Literal 测试"""

    def test_valid_statuses(self):
        """合法上市状态"""
        from app.models.stock_models import StockStatus
        for status in ("L", "D", "P"):
            stock = StockBasicInfoExtended(
                symbol="000001",
                full_symbol="000001.SZ",
                name="测试",
                status=status,
            )
            assert stock.status == status


class TestCurrencyType:
    """货币类型 Literal 测试"""

    def test_valid_currencies(self):
        """合法货币类型"""
        from app.models.stock_models import CurrencyType
        for cur in ("CNY", "HKD", "USD"):
            info = MarketInfo(
                market="CN",
                exchange="SZSE",
                exchange_name="test",
                currency=cur,
                timezone="Asia/Shanghai",
            )
            assert info.currency == cur


# ---------------------------------------------------------------------------
# MarketInfo
# ---------------------------------------------------------------------------


class TestMarketInfo:
    """市场信息模型测试"""

    def test_create_market_info(self):
        """创建市场信息"""
        info = MarketInfo(
            market="CN",
            exchange="SZSE",
            exchange_name="深圳证券交易所",
            currency="CNY",
            timezone="Asia/Shanghai",
        )
        assert info.market == "CN"
        assert info.exchange == "SZSE"
        assert info.exchange_name == "深圳证券交易所"
        assert info.currency == "CNY"
        assert info.timezone == "Asia/Shanghai"
        assert info.trading_hours is None

    def test_with_trading_hours(self):
        """带交易时间"""
        info = MarketInfo(
            market="CN",
            exchange="SSE",
            exchange_name="上海证券交易所",
            currency="CNY",
            timezone="Asia/Shanghai",
            trading_hours={
                "morning_open": "09:30",
                "morning_close": "11:30",
                "afternoon_open": "13:00",
                "afternoon_close": "15:00",
            },
        )
        assert info.trading_hours["morning_open"] == "09:30"

    def test_missing_required_fields(self):
        """缺少必填字段应报错"""
        with pytest.raises(ValidationError):
            MarketInfo(market="CN")
        with pytest.raises(ValidationError):
            MarketInfo(market="CN", exchange="SZSE")

    def test_invalid_market(self):
        """无效市场类型应报错"""
        with pytest.raises(ValidationError):
            MarketInfo(
                market="JP",
                exchange="TSE",
                exchange_name="东京",
                currency="JPY",
                timezone="Asia/Tokyo",
            )

    def test_invalid_currency(self):
        """无效货币应报错"""
        with pytest.raises(ValidationError):
            MarketInfo(
                market="CN",
                exchange="SZSE",
                exchange_name="test",
                currency="EUR",
                timezone="Asia/Shanghai",
            )


# ---------------------------------------------------------------------------
# TechnicalIndicators
# ---------------------------------------------------------------------------


class TestTechnicalIndicators:
    """技术指标模型测试"""

    def test_all_defaults_none(self):
        """所有默认值应为 None"""
        ti = TechnicalIndicators()
        assert ti.trend is None
        assert ti.oscillator is None
        assert ti.channel is None
        assert ti.volume is None
        assert ti.volatility is None
        assert ti.custom is None

    def test_with_trend_indicators(self):
        """趋势指标"""
        ti = TechnicalIndicators(
            trend={"ma5": 10.5, "ma10": 10.2, "ma20": 10.0}
        )
        assert ti.trend["ma5"] == 10.5

    def test_with_oscillator_indicators(self):
        """震荡指标"""
        ti = TechnicalIndicators(
            oscillator={"rsi14": 65.0, "kDJ_K": 70.0}
        )
        assert ti.oscillator["rsi14"] == 65.0

    def test_with_custom_indicators(self):
        """自定义指标"""
        ti = TechnicalIndicators(
            custom={"my_indicator": "bullish", "score": 0.8}
        )
        assert ti.custom["my_indicator"] == "bullish"

    def test_extra_allowed(self):
        """允许额外字段（通过自定义）"""
        ti = TechnicalIndicators(
            trend={"ma5": 10.0},
            volatility={"atr": 1.5},
        )
        assert ti.volatility["atr"] == 1.5


# ---------------------------------------------------------------------------
# StockBasicInfoExtended
# ---------------------------------------------------------------------------


class TestStockBasicInfoExtended:
    """股票基础信息扩展模型测试"""

    def test_create_minimal(self):
        """最小必填字段"""
        stock = StockBasicInfoExtended(
            symbol="000001",
            full_symbol="000001.SZ",
            name="平安银行",
        )
        assert stock.symbol == "000001"
        assert stock.full_symbol == "000001.SZ"
        assert stock.name == "平安银行"
        assert stock.code is None
        assert stock.area is None
        assert stock.industry is None
        assert stock.pe is None
        assert stock.total_mv is None

    def test_symbol_pattern_must_be_6_digits(self):
        """symbol 支持 A股(6位数字)、港股(5位数字)、美股(字母)"""
        # A股 6 位数字 — 有效
        StockBasicInfoExtended(symbol="000001", full_symbol="000001.SZ", name="test")
        # 港股 5 位数字 — 有效
        StockBasicInfoExtended(symbol="00700", full_symbol="00700.HK", name="test")
        # 美股字母 — 有效
        StockBasicInfoExtended(symbol="AAPL", full_symbol="AAPL", name="test")
        # 无效：包含小写
        with pytest.raises(ValidationError):
            StockBasicInfoExtended(symbol="aapl", full_symbol="aapl", name="test")
        # 无效：包含特殊字符
        with pytest.raises(ValidationError):
            StockBasicInfoExtended(symbol="AA@PL", full_symbol="AA@PL", name="test")

    def test_full_stock(self):
        """完整字段"""
        stock = StockBasicInfoExtended(
            symbol="000001",
            full_symbol="000001.SZ",
            name="平安银行",
            code="000001",
            area="深圳",
            industry="银行",
            market="深圳证券交易所",
            list_date="1991-04-03",
            total_mv=2500.0,
            circ_mv=2400.0,
            pe=5.2,
            pb=0.8,
            pe_ttm=5.5,
            pb_mrq=0.82,
            roe=12.5,
            turnover_rate=1.2,
            volume_ratio=0.8,
            name_en="Ping An Bank",
            board="主板",
            industry_code="J66",
            sector="金融",
            status="L",
            is_hs=True,
            total_shares=19400000000,
            float_shares=19400000000,
            currency="CNY",
            data_version=1,
        )
        assert stock.area == "深圳"
        assert stock.industry == "银行"
        assert stock.total_mv == 2500.0
        assert stock.pe == 5.2
        assert stock.status == "L"
        assert stock.is_hs is True

    def test_with_market_info(self):
        """带市场信息"""
        stock = StockBasicInfoExtended(
            symbol="000001",
            full_symbol="000001.SZ",
            name="平安银行",
            market_info=MarketInfo(
                market="CN",
                exchange="SZSE",
                exchange_name="深圳证券交易所",
                currency="CNY",
                timezone="Asia/Shanghai",
            ),
        )
        assert stock.market_info is not None
        assert stock.market_info.exchange == "SZSE"

    def test_extra_fields_allowed(self):
        """允许额外字段"""
        stock = StockBasicInfoExtended(
            symbol="000001",
            full_symbol="000001.SZ",
            name="平安银行",
            custom_field="custom_value",
        )
        assert stock.custom_field == "custom_value"

    def test_invalid_status(self):
        """无效上市状态"""
        with pytest.raises(ValidationError):
            StockBasicInfoExtended(
                symbol="000001",
                full_symbol="000001.SZ",
                name="test",
                status="X",
            )


# ---------------------------------------------------------------------------
# MarketQuotesExtended
# ---------------------------------------------------------------------------


class TestMarketQuotesExtended:
    """实时行情扩展模型测试"""

    def test_create_minimal(self):
        """最小必填字段"""
        quote = MarketQuotesExtended(symbol="000001")
        assert quote.symbol == "000001"
        assert quote.full_symbol is None
        assert quote.market is None
        assert quote.close is None
        assert quote.pct_chg is None

    def test_symbol_must_be_6_digits(self):
        """symbol 支持 A股(6位数字)、港股(5位数字)、美股(字母)"""
        # A股 6 位数字 — 有效
        MarketQuotesExtended(symbol="000001")
        # 港股 5 位数字 — 有效
        MarketQuotesExtended(symbol="00700")
        # 美股字母 — 有效
        MarketQuotesExtended(symbol="AAPL")
        # 无效：包含小写
        with pytest.raises(ValidationError):
            MarketQuotesExtended(symbol="aapl")
        # 无效：包含特殊字符
        with pytest.raises(ValidationError):
            MarketQuotesExtended(symbol="AA@PL")

    def test_full_quote(self):
        """完整行情"""
        quote = MarketQuotesExtended(
            symbol="000001",
            full_symbol="000001.SZ",
            market="CN",
            close=12.65,
            pct_chg=1.61,
            amount=1580000000,
            open=12.50,
            high=12.80,
            low=12.30,
            pre_close=12.45,
            trade_date="2024-01-15",
            current_price=12.65,
            change=0.20,
            volume=125000000,
            turnover_rate=0.65,
            volume_ratio=1.2,
        )
        assert quote.close == 12.65
        assert quote.pct_chg == 1.61
        assert quote.high == 12.80

    def test_with_bid_ask(self):
        """五档行情"""
        quote = MarketQuotesExtended(
            symbol="000001",
            bid_prices=[12.60, 12.59, 12.58, 12.57, 12.56],
            bid_volumes=[100, 200, 300, 400, 500],
            ask_prices=[12.65, 12.66, 12.67, 12.68, 12.69],
            ask_volumes=[150, 250, 350, 450, 550],
        )
        assert len(quote.bid_prices) == 5
        assert len(quote.ask_prices) == 5

    def test_market_type_validation(self):
        """市场类型验证"""
        quote = MarketQuotesExtended(symbol="000001", market="CN")
        assert quote.market == "CN"

    def test_invalid_market_type(self):
        """无效市场类型"""
        with pytest.raises(ValidationError):
            MarketQuotesExtended(symbol="000001", market="JP")

    def test_extra_fields_allowed(self):
        """允许额外字段"""
        quote = MarketQuotesExtended(
            symbol="000001",
            custom_field="value",
        )
        assert quote.custom_field == "value"

    def test_with_timestamp(self):
        """带时间戳"""
        now = datetime.now(timezone.utc)
        quote = MarketQuotesExtended(
            symbol="000001",
            timestamp=now,
        )
        assert quote.timestamp == now


# ---------------------------------------------------------------------------
# StockBasicInfoResponse
# ---------------------------------------------------------------------------


class TestStockBasicInfoResponse:
    """股票基础信息 API 响应模型测试"""

    def test_default_response(self):
        """默认响应"""
        resp = StockBasicInfoResponse()
        assert resp.success is True
        assert resp.data is None
        assert resp.message == ""

    def test_with_data(self):
        """带数据的响应"""
        stock = StockBasicInfoExtended(
            symbol="000001",
            full_symbol="000001.SZ",
            name="平安银行",
        )
        resp = StockBasicInfoResponse(data=stock)
        assert resp.data.symbol == "000001"

    def test_error_response(self):
        """错误响应"""
        resp = StockBasicInfoResponse(
            success=False,
            message="股票不存在",
        )
        assert resp.success is False
        assert resp.message == "股票不存在"


# ---------------------------------------------------------------------------
# MarketQuotesResponse
# ---------------------------------------------------------------------------


class TestMarketQuotesResponse:
    """实时行情 API 响应模型测试"""

    def test_default_response(self):
        resp = MarketQuotesResponse()
        assert resp.success is True
        assert resp.data is None

    def test_with_data(self):
        quote = MarketQuotesExtended(symbol="000001", close=12.5)
        resp = MarketQuotesResponse(data=quote)
        assert resp.data.close == 12.5


# ---------------------------------------------------------------------------
# StockListResponse
# ---------------------------------------------------------------------------


class TestStockListResponse:
    """股票列表 API 响应模型测试"""

    def test_default_response(self):
        resp = StockListResponse()
        assert resp.success is True
        assert resp.data is None
        assert resp.total == 0
        assert resp.page == 1
        assert resp.page_size == 20
        assert resp.message == ""

    def test_with_list(self):
        stocks = [
            StockBasicInfoExtended(
                symbol="000001",
                full_symbol="000001.SZ",
                name="平安银行",
            ),
            StockBasicInfoExtended(
                symbol="000002",
                full_symbol="000002.SZ",
                name="万科A",
            ),
        ]
        resp = StockListResponse(
            data=stocks,
            total=2,
            page=1,
            page_size=20,
        )
        assert len(resp.data) == 2
        assert resp.total == 2
