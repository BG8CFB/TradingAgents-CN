"""DataErrorCode 测试"""

from app.data.processor.error_codes import DataErrorCode, data_error_message, data_fail


class TestDataErrorCode:
    def test_all_codes_unique(self):
        values = [code.value for code in DataErrorCode]
        assert len(values) == len(set(values)), "错误码值不唯一"

    def test_code_ranges(self):
        for code in DataErrorCode:
            assert 1000 <= code.value <= 1099, f"{code.name}={code.value} 不在 1001-1099 范围"

    def test_message_mapping_complete(self):
        for code in DataErrorCode:
            msg = data_error_message(code)
            assert msg, f"{code.name} 缺少中文消息映射"
            assert "未知" not in msg, f"{code.name} 映射到了默认消息"

    def test_unknown_code_returns_default(self):
        msg = data_error_message(9999)
        assert "未知" in msg

    def test_data_fail_response(self):
        resp = data_fail(DataErrorCode.REFRESH_COOLDOWN)
        assert resp["success"] is False
        assert resp["data_code"] == 1001
        assert "冷却期" in resp["message"]

    def test_data_fail_custom_message(self):
        resp = data_fail(DataErrorCode.SOURCE_ALL_FAILED, message="自定义消息")
        assert resp["message"] == "自定义消息"
        assert resp["data_code"] == 1010

    def test_data_fail_with_data(self):
        resp = data_fail(DataErrorCode.VALIDATION_FAILED, data={"field": "symbol"})
        assert resp["data"] == {"field": "symbol"}
