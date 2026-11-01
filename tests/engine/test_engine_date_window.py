"""工具日期窗口防护单测（纯函数，无 I/O）。

覆盖：validate_date_window（窗口合法性 + 防前视条款）、market._d8、
news._filter_news_asof（历史分析不看分析日之后发布的新闻）。
锚定行为（窗口默认值随 trade_date）由 datasources 函数内的校验路径间接保证。
"""

from datetime import datetime

from app.engine.tools.common.param_validators import MCPToolValidators
from app.engine.tools.datasources.market import _d8
from app.engine.tools.datasources.news import _filter_news_asof


class TestValidateDateWindow:
    def test_valid_window(self):
        v = MCPToolValidators.validate_date_window("2026-01-01", "2026-02-01", as_of="2026-03-01")
        assert v.is_valid

    def test_start_after_end_rejected(self):
        v = MCPToolValidators.validate_date_window("2026-02-01", "2026-01-01")
        assert not v.is_valid
        assert "开始日期" in v.error_message

    def test_bad_format_rejected(self):
        v = MCPToolValidators.validate_date_window("2026/01/01", "2026-02-01")
        assert not v.is_valid

    def test_span_over_year_rejected(self):
        v = MCPToolValidators.validate_date_window("2024-01-01", "2026-02-01")
        assert not v.is_valid
        assert "范围过大" in v.error_message

    def test_end_beyond_as_of_rejected(self):
        """防前视：结束日期晚于分析基准日 → 拒绝（回传模型自纠）。"""
        v = MCPToolValidators.validate_date_window("2026-01-01", "2026-06-01", as_of="2026-03-01")
        assert not v.is_valid
        assert "分析基准日" in v.error_message

    def test_end_equals_as_of_allowed(self):
        v = MCPToolValidators.validate_date_window("2026-01-01", "2026-03-01", as_of="2026-03-01")
        assert v.is_valid

    def test_no_as_of_skips_lookahead_check(self):
        v = MCPToolValidators.validate_date_window("2026-01-01", "2099-01-01")
        assert not v.is_valid  # 仍被跨度检查拦截
        v2 = MCPToolValidators.validate_date_window("2026-01-01", "2026-05-01")
        assert v2.is_valid


class TestD8:
    def test_compact_to_dashed(self):
        assert _d8("20260301") == "2026-03-01"

    def test_dashed_untouched(self):
        assert _d8("2026-03-01") == "2026-03-01"


class TestNewsAsOfFilter:
    def test_filters_future_news(self):
        items = [
            {"title": "旧闻", "publish_time": datetime(2026, 1, 10, 9, 0)},
            {"title": "基准日后", "publish_time": datetime(2026, 4, 2, 9, 0)},
            {"title": "字符串时间", "publish_time": "2026-02-15 08:00:00"},
            {"title": "字符串越界", "publish_time": "2026-05-01 08:00:00"},
            {"title": "无时间戳", "publish_time": None},
        ]
        out = _filter_news_asof(items, "2026-03-01")
        titles = [i["title"] for i in out]
        assert "旧闻" in titles
        assert "字符串时间" in titles
        assert "无时间戳" in titles  # 缺失元数据保留，不误杀
        assert "基准日后" not in titles
        assert "字符串越界" not in titles

    def test_no_as_of_returns_all(self):
        items = [{"title": "x", "publish_time": datetime(2099, 1, 1)}]
        assert _filter_news_asof(items, "") == items
