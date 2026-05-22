"""DataErrorCode 测试 — 匹配新架构字符串枚举 API"""

from app.data.sources.base.error_codes import DataErrorCode


class TestDataErrorCode:
    def test_all_codes_have_string_values(self):
        for code in DataErrorCode:
            assert isinstance(code.value, str)
            assert len(code.value) > 0

    def test_key_codes_exist(self):
        assert DataErrorCode.RATE_LIMITED.value == "rate_limited"
        assert DataErrorCode.AUTH_FAILED.value == "auth_failed"
        assert DataErrorCode.NETWORK_TIMEOUT.value == "network_timeout"
        assert DataErrorCode.CONNECTION_ERROR.value == "connection_error"
        assert DataErrorCode.SERVER_ERROR.value == "server_error"
        assert DataErrorCode.DATA_INVALID.value == "data_invalid"
        assert DataErrorCode.EMPTY_RESULT.value == "empty_result"
        assert DataErrorCode.SYMBOL_NOT_FOUND.value == "symbol_not_found"
        assert DataErrorCode.NOT_SUPPORTED.value == "not_supported"
        assert DataErrorCode.UNKNOWN.value == "unknown"

    def test_all_values_unique(self):
        values = [code.value for code in DataErrorCode]
        assert len(values) == len(set(values)), "错误码值不唯一"

    def test_is_string_enum(self):
        """DataErrorCode 是 str 的子类，可直接用于字符串比较。"""
        assert DataErrorCode.RATE_LIMITED == "rate_limited"
        assert DataErrorCode.UNKNOWN == "unknown"
