"""
测试 app/core/response.py — 统一 API 响应工具函数
"""

from datetime import datetime

import pytest


class TestOk:
    """测试 ok() 成功响应函数"""

    def test_ok_returns_success_true(self):
        from app.core.response import ok
        result = ok()
        assert result["success"] is True

    def test_ok_default_data_is_none(self):
        from app.core.response import ok
        result = ok()
        assert result["data"] is None

    def test_ok_default_message(self):
        from app.core.response import ok
        result = ok()
        assert result["message"] == "ok"

    def test_ok_has_timestamp(self):
        from app.core.response import ok
        result = ok()
        assert "timestamp" in result
        parsed = datetime.fromisoformat(result["timestamp"])
        assert parsed is not None

    def test_ok_with_custom_data(self):
        from app.core.response import ok
        data = {"stock": "000001", "price": 10.5}
        result = ok(data=data)
        assert result["data"] == data
        assert result["success"] is True

    def test_ok_with_custom_message(self):
        from app.core.response import ok
        result = ok(message="查询成功")
        assert result["message"] == "查询成功"

    def test_ok_with_data_and_message(self):
        from app.core.response import ok
        data = [1, 2, 3]
        result = ok(data=data, message="获取列表成功")
        assert result["data"] == data
        assert result["message"] == "获取列表成功"
        assert result["success"] is True

    def test_ok_timestamp_is_recent(self):
        from app.core.response import ok
        from app.utils.timezone import now_tz

        before = now_tz()
        result = ok()
        after = now_tz()

        ts = datetime.fromisoformat(result["timestamp"])
        assert before <= ts or (ts - before).total_seconds() < 1
        assert ts <= after or (ts - after).total_seconds() < 1


class TestFail:
    """测试 fail() 失败响应函数"""

    def test_fail_returns_success_false(self):
        from app.core.response import fail
        result = fail()
        assert result["success"] is False

    def test_fail_default_message(self):
        from app.core.response import fail
        result = fail()
        assert result["message"] == "error"

    def test_fail_default_code(self):
        from app.core.response import fail
        result = fail()
        assert result["code"] == 500

    def test_fail_has_timestamp(self):
        from app.core.response import fail
        result = fail()
        assert "timestamp" in result

    def test_fail_with_custom_message(self):
        from app.core.response import fail
        result = fail(message="参数错误")
        assert result["message"] == "参数错误"

    def test_fail_with_custom_code(self):
        from app.core.response import fail
        result = fail(code=400)
        assert result["code"] == 400

    def test_fail_with_data(self):
        from app.core.response import fail
        data = {"field": "email", "error": "格式错误"}
        result = fail(data=data)
        assert result["data"] == data

    def test_fail_default_data_is_none(self):
        from app.core.response import fail
        result = fail()
        assert result["data"] is None

    def test_fail_with_all_params(self):
        from app.core.response import fail
        data = {"detail": "权限不足"}
        result = fail(message="禁止访问", code=403, data=data)
        assert result["success"] is False
        assert result["message"] == "禁止访问"
        assert result["code"] == 403
        assert result["data"] == data
        assert "timestamp" in result


class TestSafeErrorMessage:
    """测试 safe_error_message() 安全错误消息函数"""

    def test_debug_mode_returns_detailed_message(self):
        """DEBUG 模式下返回详细错误消息"""
        from app.core.response import safe_error_message

        error = ValueError("数据库连接失败")
        result = safe_error_message(error)
        assert "数据库连接失败" in result
        assert "操作失败" in result

    def test_debug_mode_with_custom_default(self):
        from app.core.response import safe_error_message

        error = RuntimeError("服务不可用")
        result = safe_error_message(error, default="服务异常")
        assert "服务异常" in result
        assert "服务不可用" in result

    def test_debug_false_returns_generic_message(self):
        """DEBUG=False 时返回通用错误消息"""
        from app.core.response import safe_error_message
        from app.core.config import settings

        original_debug = settings.DEBUG
        settings.DEBUG = False
        try:
            error = ValueError("数据库密码泄露了 secret_password_123")
            result = safe_error_message(error)
            assert result == "操作失败，请稍后重试"
            assert "secret_password_123" not in result
        finally:
            settings.DEBUG = original_debug

    def test_debug_false_with_custom_default(self):
        from app.core.response import safe_error_message
        from app.core.config import settings

        original_debug = settings.DEBUG
        settings.DEBUG = False
        try:
            error = Exception("内部错误详情")
            result = safe_error_message(error, default="系统繁忙")
            assert result == "系统繁忙"
        finally:
            settings.DEBUG = original_debug

    def test_default_message_content(self):
        from app.core.response import safe_error_message

        error = Exception("test error")
        result = safe_error_message(error)
        assert isinstance(result, str)
        assert len(result) > 0
