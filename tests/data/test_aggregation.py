"""日线→周线/月线聚合规则单元测试"""

from app.data.processor.aggregation import aggregate_period


class TestWeeklyAggregation:
    """周线聚合测试"""

    def test_basic_weekly_aggregation(self):
        daily = [
            {"trade_date": "2026-05-11", "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.3,
             "volume": 1000, "amount": 10000, "symbol": "000001"},
            {"trade_date": "2026-05-12", "open": 10.3, "high": 10.8, "low": 10.1, "close": 10.6,
             "volume": 1200, "amount": 12000, "symbol": "000001"},
            {"trade_date": "2026-05-13", "open": 10.6, "high": 11.0, "low": 10.4, "close": 10.8,
             "volume": 1100, "amount": 11000, "symbol": "000001"},
            {"trade_date": "2026-05-14", "open": 10.8, "high": 11.2, "low": 10.7, "close": 11.0,
             "volume": 1300, "amount": 13000, "symbol": "000001"},
            {"trade_date": "2026-05-15", "open": 11.0, "high": 11.5, "low": 10.9, "close": 11.3,
             "volume": 1400, "amount": 14000, "symbol": "000001"},
        ]

        result = aggregate_period(daily, period="weekly")

        assert len(result) == 1
        week = result[0]
        assert week["open"] == 10.0
        assert week["close"] == 11.3
        assert week["high"] == 11.5
        assert week["low"] == 9.8
        assert week["volume"] == 6000
        assert week["amount"] == 60000
        assert week["symbol"] == "000001"

    def test_empty_input(self):
        result = aggregate_period([], period="weekly")
        assert result == []

    def test_single_day(self):
        daily = [
            {"trade_date": "2026-05-15", "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.3,
             "volume": 1000, "amount": 10000, "symbol": "000001"},
        ]

        result = aggregate_period(daily, period="weekly")

        assert len(result) == 1
        assert result[0]["open"] == 10.0
        assert result[0]["close"] == 10.3


class TestMonthlyAggregation:
    """月线聚合测试"""

    def test_basic_monthly_aggregation(self):
        daily = [
            {"trade_date": "2026-05-04", "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.3,
             "volume": 1000, "amount": 10000, "symbol": "000001"},
            {"trade_date": "2026-05-15", "open": 10.3, "high": 11.0, "low": 10.1, "close": 10.8,
             "volume": 1200, "amount": 12000, "symbol": "000001"},
        ]

        result = aggregate_period(daily, period="monthly")

        assert len(result) == 1
        month = result[0]
        assert month["open"] == 10.0
        assert month["close"] == 10.8
        assert month["volume"] == 2200
