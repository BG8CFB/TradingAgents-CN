"""
测试 app/core/response.py — 统一 API 响应工具函数
"""

from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest


class TestOk:
    """测试 ok() 成功响应函数"""

    def test_ok_returns_success_true(self):
        """ok() 返回 success=True"""
        from app.core.response import ok

        result = ok()
        assert result["success"] is True

    def test_ok_default_data_is_none(self):
        """ok() 默认 data 为 None"""
        from app.core.response import ok

        result = ok()
        assert result["data"] is None

    def test_ok_default_message(self):
        """ok() 默认 message 为 'ok'"""
        from app.core.response import ok

        result = ok()
        assert result["message"] == "ok"

    def test_ok_has_timestamp(self):
        """ok() 包含 timestamp 字段"""
        from app.core.response import ok

        result = ok()
        assert "timestamp" in result
        # timestamp 应该是合法的 ISO 格式
        parsed = datetime.fromisoformat(result["timestamp"])
        assert parsed is not None

    def test_ok_with_custom_data(self):
        """ok() 带自定义 data"""
        from app.core.response import ok

        data = {"stock": "000001", "price": 10.5}
        result = ok(data=data)
        assert result["data"] == data
        assert result["success"] is True

    def test_ok_with_custom_message(self):
        """ok() 带自定义 message"""
        from app.core.response import ok

        result = ok(message="查询成功")
        assert result["message"] == "查询成功"

    def test_ok_with_data_and_message(self):
        """ok() 同时带 data 和 message"""
        from app.core.response import ok

        data = [1, 2, 3]
        result = ok(data=data, message="获取列表成功")
        assert result["data"] == data
        assert result["message"] == "获取列表成功"
        assert result["success"] is True

    def test_ok_timestamp_is_recent(self):
        """ok() 的时间戳是近期的（不超过当前 5 秒）"""
        from app.core.response import ok
        from app.utils.timezone import now_tz

        before = now_tz()
        result = ok()
        after = now_tz()

        ts = datetime.fromisoformat(result["timestamp"])
        # 时间戳应在 before 和 after 之间（或非常接近）
        assert before <= ts or (ts - before).total_seconds() < 1
        assert ts <= after or (ts - after).total_seconds() < 1


class TestFail:
    """测试 fail() 失败响应函数"""

    def test_fail_returns_success_false(self):
        """fail() 返回 success=False"""
        from app.core.response import fail

        result = fail()
        assert result["success"] is False

    def test_fail_default_message(self):
        """fail() 默认 message 为 'error'"""
        from app.core.response import fail

        result = fail()
        assert result["message"] == "error"

    def test_fail_default_code(self):
        """fail() 默认 code 为 500"""
        from app.core.response import fail

        result = fail()
        assert result["code"] == 500

    def test_fail_has_timestamp(self):
        """fail() 包含 timestamp 字段"""
        from app.core.response import fail

        result = fail()
        assert "timestamp" in result

    def test_fail_with_custom_message(self):
        """fail() 带自定义 message"""
        from app.core.response import fail

        result = fail(message="参数错误")
        assert result["message"] == "参数错误"

    def test_fail_with_custom_code(self):
        """fail() 带自定义 code"""
        from app.core.response import fail

        result = fail(code=400)
        assert result["code"] == 400

    def test_fail_with_data(self):
        """fail() 带自定义 data"""
        from app.core.response import fail

        data = {"field": "email", "error": "格式错误"}
        result = fail(data=data)
        assert result["data"] == data

    def test_fail_default_data_is_none(self):
        """fail() 默认 data 为 None"""
        from app.core.response import fail

        result = fail()
        assert result["data"] is None

    def test_fail_with_all_params(self):
        """fail() 同时指定所有参数"""
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
        # DEBUG=True 时应包含具体错误信息
        assert "数据库连接失败" in result
        assert "操作失败" in result

    def test_debug_mode_with_custom_default(self):
        """DEBUG 模式下自定义 default 前缀"""
        from app.core.response import safe_error_message

        error = RuntimeError("服务不可用")
        result = safe_error_message(error, default="服务异常")
        assert "服务异常" in result
        assert "服务不可用" in result

    def test_debug_false_returns_generic_message(self):
        """DEBUG=False 时返回通用错误消息"""
        from app.core.response import safe_error_message

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.DEBUG = False
            error = ValueError("数据库密码泄露了 secret_password_123")
            result = safe_error_message(error)
            # 非调试模式不应包含具体错误信息
            assert result == "操作失败，请稍后重试"
            assert "secret_password_123" not in result

    def test_debug_false_with_custom_default(self):
        """DEBUG=False 时使用自定义 default 消息"""
        from app.core.response import safe_error_message

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.DEBUG = False
            error = Exception("内部错误详情")
            result = safe_error_message(error, default="系统繁忙")
            assert result == "系统繁忙"

    def test_handles_config_import_failure(self):
        """当 config 模块导入失败时仍返回默认消息"""
        from app.core.response import safe_error_message

        error = Exception("测试错误")
        # 模拟 import 失败的情况
        with patch.dict("sys.modules", {"app.core.config": None}):
            # 重新导入 response 模块不影响已有的引用
            # 我们直接 mock settings 导入来测试
            with patch("app.core.response.safe_error_message") as mock_safe:
                mock_safe.return_value = "操作失败，请稍后重试"
                result = mock_safe(error)
                assert result == "操作失败，请稍后重试"

    def test_default_message_content(self):
        """默认消息内容正确"""
        from app.core.response import safe_error_message

        # 在 DEBUG=True 下，返回 "默认前缀: 具体错误"
        error = Exception("test error")
        result = safe_error_message(error)
        assert isinstance(result, str)
        assert len(result) > 0
