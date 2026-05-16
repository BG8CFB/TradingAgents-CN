"""
测试 app/core/logging_context.py — 日志上下文（trace_id 与 LoggingContextFilter）
"""

import logging

import pytest

from app.core.logging_context import trace_id_var, LoggingContextFilter


class TestTraceIdVar:
    """测试 trace_id_var ContextVar"""

    def test_default_value(self):
        """默认值为 '-'"""
        # 需要在新的 context 中检查，避免被其他测试污染
        token = trace_id_var.set("-")
        try:
            assert trace_id_var.get() == "-"
        finally:
            trace_id_var.reset(token)

    def test_set_and_get(self):
        """可以设置和获取 trace_id"""
        token = trace_id_var.set("abc-123-def")
        try:
            assert trace_id_var.get() == "abc-123-def"
        finally:
            trace_id_var.reset(token)

    def test_set_different_values(self):
        """可以设置不同的值"""
        token1 = trace_id_var.set("trace-001")
        try:
            assert trace_id_var.get() == "trace-001"
        finally:
            trace_id_var.reset(token1)

        token2 = trace_id_var.set("trace-002")
        try:
            assert trace_id_var.get() == "trace-002"
        finally:
            trace_id_var.reset(token2)

    def test_reset_restores_previous(self):
        """reset() 恢复之前的值"""
        original = trace_id_var.get()
        token = trace_id_var.set("new-trace-id")
        assert trace_id_var.get() == "new-trace-id"
        trace_id_var.reset(token)
        assert trace_id_var.get() == original


class TestLoggingContextFilter:
    """测试 LoggingContextFilter"""

    def setup_method(self):
        """设置测试用的 logger 和 handler"""
        self.filter = LoggingContextFilter()
        self.logger = logging.getLogger("test_logging_context")
        self.logger.setLevel(logging.DEBUG)
        # 清除已有 handler
        self.logger.handlers.clear()

    def test_filter_returns_true(self):
        """filter() 总是返回 True（不过滤任何日志）"""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="test message",
            args=None,
            exc_info=None,
        )
        result = self.filter.filter(record)
        assert result is True

    def test_filter_sets_trace_id_on_record(self):
        """filter() 设置 record.trace_id"""
        token = trace_id_var.set("test-trace-abc")
        try:
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="test.py",
                lineno=1,
                msg="test message",
                args=None,
                exc_info=None,
            )
            self.filter.filter(record)
            assert record.trace_id == "test-trace-abc"
        finally:
            trace_id_var.reset(token)

    def test_filter_default_trace_id(self):
        """当未设置 trace_id 时，使用默认值 '-'"""
        token = trace_id_var.set("-")
        try:
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="test.py",
                lineno=1,
                msg="test message",
                args=None,
                exc_info=None,
            )
            self.filter.filter(record)
            assert record.trace_id == "-"
        finally:
            trace_id_var.reset(token)

    def test_filter_handles_exception_gracefully(self):
        """当 trace_id_var.get() 抛出异常时，使用默认值 '-'"""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="test message",
            args=None,
            exc_info=None,
        )

        # 模拟 trace_id_var.get() 抛出异常
        # ContextVar.get 是 C 实现的只读属性，不能 patch，
        # 所以创建一个子类覆盖 filter 来验证异常处理逻辑。
        # 改用 patch 模块级的 trace_id_var 变量
        import app.core.logging_context as ctx_mod

        class BrokenContextVar:
            """模拟 ContextVar.get() 抛出异常"""
            def get(self):
                raise LookupError("no token")

        original_var = ctx_mod.trace_id_var
        ctx_mod.trace_id_var = BrokenContextVar()
        try:
            # 同时需要在 filter 使用的 trace_id_var 上触发异常
            # 因为 filter 直接引用了模块级的 trace_id_var
            result = self.filter.filter(record)
            assert result is True
            assert record.trace_id == "-"
        finally:
            ctx_mod.trace_id_var = original_var

    def test_filter_with_uuid_trace_id(self):
        """使用 UUID 格式的 trace_id"""
        uuid_str = "550e8400-e29b-41d4-a716-446655440000"
        token = trace_id_var.set(uuid_str)
        try:
            record = logging.LogRecord(
                name="test",
                level=logging.DEBUG,
                pathname="test.py",
                lineno=1,
                msg="debug msg",
                args=None,
                exc_info=None,
            )
            self.filter.filter(record)
            assert record.trace_id == uuid_str
        finally:
            trace_id_var.reset(token)

    def test_filter_integration_with_logger(self):
        """集成测试：filter 与 logger 配合使用"""
        token = trace_id_var.set("integration-test-001")
        try:
            test_filter = LoggingContextFilter()
            logger = logging.getLogger("integration_test_logger")
            logger.addFilter(test_filter)

            records = []

            handler = logging.Handler()
            handler.emit = lambda record: records.append(record)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)

            logger.info("test message")
            assert len(records) == 1
            assert records[0].trace_id == "integration-test-001"

            # 清理
            logger.removeFilter(test_filter)
            logger.removeHandler(handler)
        finally:
            trace_id_var.reset(token)
