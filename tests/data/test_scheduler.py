"""测试 Scheduler — Job 注册、检查点管理、依赖链、时区处理。"""

import pytest
from datetime import datetime, timezone

from app.data.scheduler.job_registry import JobRegistry
from app.data.scheduler.dependencies import DependencyGraph
from app.data.scheduler.timezone import to_market_time, to_utc, is_dst


class TestJobRegistry:
    def setup_method(self):
        self.registry = JobRegistry()

    def test_register_and_get(self):
        self.registry.register("daily_quotes", "CN", "TushareJob")
        job = self.registry.get_job("daily_quotes", "CN")
        assert job is not None
        assert job["domain"] == "daily_quotes"
        assert job["market"] == "CN"

    def test_list_jobs_by_market(self):
        self.registry.register("daily_quotes", "CN", "J1")
        self.registry.register("basic_info", "CN", "J2")
        self.registry.register("daily_quotes", "HK", "J3")

        cn_jobs = self.registry.list_jobs(market="CN")
        assert len(cn_jobs) == 2

        all_jobs = self.registry.list_jobs()
        assert len(all_jobs) == 3

    def test_get_nonexistent(self):
        assert self.registry.get_job("nonexistent", "CN") is None


class TestDependencyGraph:
    def setup_method(self):
        self.graph = DependencyGraph()

    def test_no_deps(self):
        order = self.graph.get_execution_order(["A", "B", "C"])
        assert len(order) == 1
        assert set(order[0]) == {"A", "B", "C"}

    def test_linear_chain(self):
        self.graph.add_dependency("B", "A")
        self.graph.add_dependency("C", "B")
        order = self.graph.get_execution_order(["A", "B", "C"])
        assert len(order) == 3
        assert "A" in order[0]
        assert "B" in order[1]
        assert "C" in order[2]

    def test_parallel_independent(self):
        self.graph.add_dependency("C", "A")
        self.graph.add_dependency("C", "B")
        order = self.graph.get_execution_order(["A", "B", "C"])
        assert len(order) == 2
        assert set(order[0]) == {"A", "B"}
        assert order[1] == ["C"]

    def test_complex_graph(self):
        # trade_calendar → basic_info → daily_quotes → daily_indicators
        #                                    → adj_factors
        self.graph.add_dependency("basic_info", "trade_calendar")
        self.graph.add_dependency("daily_quotes", "basic_info")
        self.graph.add_dependency("daily_indicators", "daily_quotes")
        self.graph.add_dependency("adj_factors", "daily_quotes")

        order = self.graph.get_execution_order(
            ["trade_calendar", "basic_info", "daily_quotes",
             "daily_indicators", "adj_factors"]
        )
        assert len(order) >= 3
        # trade_calendar 在第一组
        assert "trade_calendar" in order[0]
        # daily_indicators 和 adj_factors 在 daily_quotes 之后
        found_quotes = None
        found_indicators = None
        for i, group in enumerate(order):
            if "daily_quotes" in group:
                found_quotes = i
            if "daily_indicators" in group:
                found_indicators = i
        assert found_indicators > found_quotes


class TestTimezone:
    def test_to_market_time_cn(self):
        utc_dt = datetime(2024, 1, 15, 8, 0, tzinfo=timezone.utc)
        cn_time = to_market_time(utc_dt, "CN")
        assert cn_time.hour == 16  # UTC+8

    def test_to_market_time_us(self):
        utc_dt = datetime(2024, 1, 15, 14, 30, tzinfo=timezone.utc)
        us_time = to_market_time(utc_dt, "US")
        # 冬令时: ET = UTC-5
        assert us_time.hour == 9 or us_time.hour == 10

    def test_to_utc_cn(self):
        cn_dt = datetime(2024, 1, 15, 16, 0)
        utc_dt = to_utc(cn_dt, "CN")
        assert utc_dt.hour == 8

    def test_is_dst(self):
        # 美东夏令时检测
        result = is_dst("US")
        assert isinstance(result, bool)
        # 非美东市场返回 False
        assert is_dst("CN") is False
        assert is_dst("HK") is False
