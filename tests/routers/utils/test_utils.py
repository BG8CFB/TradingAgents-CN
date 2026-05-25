"""
工具模块单元测试
覆盖 stock_utils, time_utils, stock_validator
"""

import pytest
from datetime import datetime, timezone

from app.utils.stock_utils import (
    StockUtils,
    StockMarket,
    is_china_stock,
    is_hk_stock,
    is_us_stock,
    get_stock_market_info,
)
from app.utils.time_utils import (
    now_utc,
    format_iso,
    format_date_short,
    format_date_compact,
    format_datetime,
    now_timestamp,
    datetime_to_timestamp,
    timestamp_to_datetime,
    ensure_tz,
    parse_date_aware,
    fromtimestamp_aware,
)


# ============================================================================
# stock_utils 测试
# ============================================================================


class TestStockUtilsIdentifyMarket:
    """StockUtils.identify_stock_market 测试"""

    def test_china_a_pure_6digit(self):
        """6位纯数字应为 A 股"""
        assert StockUtils.identify_stock_market("000001") == StockMarket.CHINA_A
        assert StockUtils.identify_stock_market("600519") == StockMarket.CHINA_A
        assert StockUtils.identify_stock_market("300750") == StockMarket.CHINA_A

    def test_china_a_with_suffix(self):
        """带 .SZ/.SH/.BJ 后缀应为 A 股"""
        assert StockUtils.identify_stock_market("000001.SZ") == StockMarket.CHINA_A
        assert StockUtils.identify_stock_market("600519.SH") == StockMarket.CHINA_A
        assert StockUtils.identify_stock_market("430001.BJ") == StockMarket.CHINA_A

    def test_hk_stock_with_hk_suffix(self):
        """带 .HK 后缀应为港股"""
        assert StockUtils.identify_stock_market("00700.HK") == StockMarket.HONG_KONG
        assert StockUtils.identify_stock_market("0700.HK") == StockMarket.HONG_KONG
        assert StockUtils.identify_stock_market("9988.HK") == StockMarket.HONG_KONG

    def test_hk_stock_pure_digits(self):
        """纯1-5位数字（非6位）应识别为港股"""
        assert StockUtils.identify_stock_market("700") == StockMarket.HONG_KONG
        assert StockUtils.identify_stock_market("9988") == StockMarket.HONG_KONG

    def test_us_stock_letters(self):
        """1-5位字母应为美股"""
        assert StockUtils.identify_stock_market("AAPL") == StockMarket.US
        assert StockUtils.identify_stock_market("TSLA") == StockMarket.US
        assert StockUtils.identify_stock_market("B") == StockMarket.US

    def test_unknown_empty(self):
        """空字符串应为未知"""
        assert StockUtils.identify_stock_market("") == StockMarket.UNKNOWN

    def test_unknown_none(self):
        """None 应为未知"""
        assert StockUtils.identify_stock_market(None) == StockMarket.UNKNOWN

    def test_case_insensitive(self):
        """大小写不敏感"""
        assert StockUtils.identify_stock_market("aapl") == StockMarket.US
        assert StockUtils.identify_stock_market("000001.sz") == StockMarket.CHINA_A

    def test_strips_whitespace(self):
        """应去除空白"""
        assert StockUtils.identify_stock_market("  AAPL  ") == StockMarket.US
        assert StockUtils.identify_stock_market(" 000001 ") == StockMarket.CHINA_A

    def test_unknown_gibberish(self):
        """乱码应为未知"""
        assert StockUtils.identify_stock_market("@#$%") == StockMarket.UNKNOWN
        assert StockUtils.identify_stock_market("ABC123") == StockMarket.UNKNOWN


class TestStockUtilsIsChinaStock:
    """is_china_stock 测试"""

    def test_china_stocks(self):
        assert is_china_stock("000001") is True
        assert is_china_stock("600519.SH") is True

    def test_non_china_stocks(self):
        assert is_china_stock("AAPL") is False
        assert is_china_stock("00700.HK") is False


class TestStockUtilsIsHkStock:
    """is_hk_stock 测试"""

    def test_hk_stocks(self):
        assert is_hk_stock("00700.HK") is True
        assert is_hk_stock("700") is True

    def test_non_hk_stocks(self):
        assert is_hk_stock("000001") is False
        assert is_hk_stock("AAPL") is False


class TestStockUtilsIsUsStock:
    """is_us_stock 测试"""

    def test_us_stocks(self):
        assert is_us_stock("AAPL") is True
        assert is_us_stock("TSLA") is True

    def test_non_us_stocks(self):
        assert is_us_stock("000001") is False
        assert is_us_stock("00700.HK") is False


class TestStockUtilsGetCurrencyInfo:
    """get_currency_info 测试"""

    def test_china_currency(self):
        name, symbol = StockUtils.get_currency_info("000001")
        assert name == "人民币"
        assert symbol == "¥"

    def test_hk_currency(self):
        name, symbol = StockUtils.get_currency_info("00700.HK")
        assert name == "港币"
        assert symbol == "HK$"

    def test_us_currency(self):
        name, symbol = StockUtils.get_currency_info("AAPL")
        assert name == "美元"
        assert symbol == "$"

    def test_unknown_currency(self):
        name, symbol = StockUtils.get_currency_info("")
        assert name == "未知"
        assert symbol == "?"


class TestStockUtilsGetDataSource:
    """get_data_source 测试"""

    def test_china_source(self):
        assert StockUtils.get_data_source("000001") == "china_unified"

    def test_hk_source(self):
        assert StockUtils.get_data_source("00700.HK") == "yahoo_finance"

    def test_us_source(self):
        assert StockUtils.get_data_source("AAPL") == "yahoo_finance"

    def test_unknown_source(self):
        assert StockUtils.get_data_source("") == "unknown"


class TestStockUtilsNormalizeHkTicker:
    """normalize_hk_ticker 测试"""

    def test_pure_digits_to_5digit_hk(self):
        """纯数字补齐为 5 位并加 .HK"""
        assert StockUtils.normalize_hk_ticker("700") == "00700.HK"
        assert StockUtils.normalize_hk_ticker("9988") == "09988.HK"

    def test_already_correct_format(self):
        """已是正确格式直接返回"""
        assert StockUtils.normalize_hk_ticker("00700.HK") == "00700.HK"

    def test_short_hk_suffix(self):
        """短位 .HK 格式补齐"""
        assert StockUtils.normalize_hk_ticker("700.HK") == "00700.HK"

    def test_empty_input(self):
        """空输入直接返回"""
        assert StockUtils.normalize_hk_ticker("") == ""
        assert StockUtils.normalize_hk_ticker(None) is None


class TestStockUtilsGetMarketInfo:
    """get_market_info 测试"""

    def test_china_market_info(self):
        info = StockUtils.get_market_info("000001")
        assert info["market"] == "china_a"
        assert info["market_name"] == "中国A股"
        assert info["is_china"] is True
        assert info["is_hk"] is False
        assert info["is_us"] is False

    def test_hk_market_info(self):
        info = StockUtils.get_market_info("00700.HK")
        assert info["market"] == "hong_kong"
        assert info["market_name"] == "港股"
        assert info["is_hk"] is True

    def test_us_market_info(self):
        info = StockUtils.get_market_info("AAPL")
        assert info["market"] == "us"
        assert info["market_name"] == "美股"
        assert info["is_us"] is True


class TestGetStockMarketInfoCompat:
    """向后兼容的 get_stock_market_info 函数测试"""

    def test_compat_function(self):
        info = get_stock_market_info("000001")
        assert info["market"] == "china_a"


# ============================================================================
# time_utils 测试
# ============================================================================


class TestNowUtc:
    """now_utc 测试"""

    def test_returns_datetime(self):
        """应返回 datetime"""
        result = now_utc()
        assert isinstance(result, datetime)

    def test_has_utc_timezone(self):
        """应带 UTC 时区"""
        result = now_utc()
        assert result.tzinfo is not None
        assert result.tzinfo == timezone.utc

    def test_close_to_current_time(self):
        """应接近当前时间"""
        before = datetime.now(timezone.utc)
        result = now_utc()
        after = datetime.now(timezone.utc)
        assert before <= result <= after


class TestFormatIso:
    """format_iso 测试"""

    def test_utc_datetime(self):
        """UTC 时间格式化"""
        dt = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        result = format_iso(dt)
        assert "2024-01-15" in result
        assert "10:30:00" in result

    def test_none_returns_none(self):
        """None 返回 None"""
        assert format_iso(None) is None

    def test_naive_datetime_gets_tz(self):
        """naive datetime 应自动添加时区"""
        dt = datetime(2024, 6, 15, 12, 0, 0)
        result = format_iso(dt)
        assert result is not None
        assert "2024-06-15" in result


class TestFormatDateShort:
    """format_date_short 测试"""

    def test_format(self):
        dt = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        assert format_date_short(dt) == "2024-01-15"

    def test_none_returns_none(self):
        assert format_date_short(None) is None


class TestFormatDateCompact:
    """format_date_compact 测试"""

    def test_format(self):
        dt = datetime(2024, 1, 15, tzinfo=timezone.utc)
        assert format_date_compact(dt) == "20240115"

    def test_none_returns_none(self):
        assert format_date_compact(None) is None


class TestFormatDatetime:
    """format_datetime 测试"""

    def test_format(self):
        dt = datetime(2024, 1, 15, 10, 30, 45, tzinfo=timezone.utc)
        assert format_datetime(dt) == "2024-01-15 10:30:45"

    def test_none_returns_none(self):
        assert format_datetime(None) is None


class TestNowTimestamp:
    """now_timestamp 测试"""

    def test_returns_float(self):
        result = now_timestamp()
        assert isinstance(result, float)

    def test_positive(self):
        assert now_timestamp() > 0


class TestDatetimeToTimestamp:
    """datetime_to_timestamp 测试"""

    def test_utc_datetime(self):
        dt = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        ts = datetime_to_timestamp(dt)
        assert isinstance(ts, float)
        assert ts > 0

    def test_none_returns_none(self):
        assert datetime_to_timestamp(None) is None


class TestTimestampToDatetime:
    """timestamp_to_datetime 测试"""

    def test_utc_conversion(self):
        """默认转换为配置时区"""
        ts = 1704067200.0  # 2024-01-01 00:00:00 UTC
        dt = timestamp_to_datetime(ts, to_config_tz=False)
        assert dt is not None
        assert dt.tzinfo is not None
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 1

    def test_none_returns_none(self):
        assert timestamp_to_datetime(None) is None


class TestEnsureTz:
    """ensure_tz 测试"""

    def test_none_returns_none(self):
        assert ensure_tz(None) is None

    def test_already_aware(self):
        """已有 timezone 的保持不变"""
        dt = datetime(2024, 1, 1, tzinfo=timezone.utc)
        result = ensure_tz(dt)
        assert result.tzinfo is not None

    def test_naive_gets_timezone(self):
        """naive datetime 应添加时区"""
        dt = datetime(2024, 1, 1)
        result = ensure_tz(dt)
        assert result.tzinfo is not None

    def test_naive_default_to_utc(self):
        """default_to_utc=True 时 naive datetime 添加 UTC"""
        dt = datetime(2024, 1, 1)
        result = ensure_tz(dt, default_to_utc=True)
        assert result.tzinfo == timezone.utc


class TestParseDateAware:
    """parse_date_aware 测试"""

    def test_valid_date_string(self):
        """合法日期字符串"""
        dt = parse_date_aware("2024-01-01", to_config_tz=False)
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 1
        assert dt.tzinfo is not None

    def test_empty_raises(self):
        """空字符串应报错"""
        with pytest.raises(ValueError, match="cannot be empty"):
            parse_date_aware("")

    def test_none_raises(self):
        """None 应报错"""
        with pytest.raises(ValueError):
            parse_date_aware(None)


class TestFromtimestampAware:
    """fromtimestamp_aware 测试"""

    def test_utc_output(self):
        """UTC 输出"""
        dt = fromtimestamp_aware(1704067200.0, to_config_tz=False)
        assert dt.year == 2024
        assert dt.tzinfo == timezone.utc


# ============================================================================
# stock_validator 测试（仅格式验证部分，不涉及外部调用）
# ============================================================================


class TestStockDataPreparationResult:
    """StockDataPreparationResult 数据类测试"""

    def test_create_result(self):
        from app.utils.stock_validator import StockDataPreparationResult
        result = StockDataPreparationResult(
            is_valid=True,
            stock_code="000001",
            market_type="A股",
            stock_name="平安银行",
        )
        assert result.is_valid is True
        assert result.stock_code == "000001"
        assert result.market_type == "A股"
        assert result.stock_name == "平安银行"
        assert result.error_message == ""
        assert result.suggestion == ""
        assert result.has_historical_data is False
        assert result.has_basic_info is False

    def test_invalid_result(self):
        from app.utils.stock_validator import StockDataPreparationResult
        result = StockDataPreparationResult(
            is_valid=False,
            stock_code="",
            error_message="代码不能为空",
            suggestion="请输入有效代码",
        )
        assert result.is_valid is False
        assert result.error_message == "代码不能为空"

    def test_to_dict(self):
        from app.utils.stock_validator import StockDataPreparationResult
        result = StockDataPreparationResult(
            is_valid=True,
            stock_code="000001",
            market_type="A股",
            stock_name="平安银行",
            has_historical_data=True,
            has_basic_info=True,
            data_period_days=365,
            cache_status="已缓存",
        )
        d = result.to_dict()
        assert d["is_valid"] is True
        assert d["stock_code"] == "000001"
        assert d["has_historical_data"] is True
        assert d["data_period_days"] == 365
        assert d["cache_status"] == "已缓存"


class TestStockDataPreparerFormatValidation:
    """StockDataPreparer 格式验证测试（不涉及外部数据源）"""

    def setup_method(self):
        from app.utils.stock_validator import StockDataPreparer
        self.preparer = StockDataPreparer()

    def test_validate_format_empty_code(self):
        """空代码应无效"""
        result = self.preparer._validate_format("", "A股")
        assert result.is_valid is False
        assert "不能为空" in result.error_message

    def test_validate_format_too_long(self):
        """超长代码应无效"""
        result = self.preparer._validate_format("12345678901", "A股")
        assert result.is_valid is False

    def test_validate_format_china_valid(self):
        """合法 A 股代码"""
        result = self.preparer._validate_format("000001", "A股")
        assert result.is_valid is True
        assert result.market_type == "A股"

    def test_validate_format_china_invalid(self):
        """非法 A 股代码"""
        result = self.preparer._validate_format("00001", "A股")
        assert result.is_valid is False
        result = self.preparer._validate_format("ABCDEF", "A股")
        assert result.is_valid is False

    def test_validate_format_hk_valid(self):
        """合法港股代码"""
        result = self.preparer._validate_format("00700.HK", "港股")
        assert result.is_valid is True
        result = self.preparer._validate_format("0700", "港股")
        assert result.is_valid is True

    def test_validate_format_hk_invalid(self):
        """非法港股代码"""
        result = self.preparer._validate_format("AAPL", "港股")
        assert result.is_valid is False

    def test_validate_format_us_valid(self):
        """合法美股代码"""
        result = self.preparer._validate_format("AAPL", "美股")
        assert result.is_valid is True

    def test_validate_format_us_invalid(self):
        """非法美股代码"""
        result = self.preparer._validate_format("123456", "美股")
        assert result.is_valid is False

    def test_detect_market_type_china(self):
        """自动检测 A 股"""
        assert self.preparer._detect_market_type("000001") == "A股"
        assert self.preparer._detect_market_type("600519") == "A股"

    def test_detect_market_type_hk(self):
        """自动检测港股"""
        assert self.preparer._detect_market_type("00700.HK") == "港股"
        assert self.preparer._detect_market_type("0700") == "港股"

    def test_detect_market_type_us(self):
        """自动检测美股"""
        assert self.preparer._detect_market_type("AAPL") == "美股"
        assert self.preparer._detect_market_type("TSLA") == "美股"

    def test_detect_market_type_unknown(self):
        """无法识别"""
        assert self.preparer._detect_market_type("@#$%") == "未知"
