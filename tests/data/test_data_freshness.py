"""Reader 新鲜度判定测试"""

from unittest.mock import patch, MagicMock


class TestFreshnessCheck:
    def test_freshness_unknown_for_missing_rule(self):
        from app.data.reader import check_freshness
        result = check_freshness("CN", "000001", "nonexistent_domain")
        assert result == "unknown"

    @patch("app.data.reader._query_collection")
    def test_freshness_stale_when_no_data(self, mock_query):
        mock_query.return_value = []
        from app.data.reader import check_freshness
        result = check_freshness("CN", "000001", "basic_info")
        assert result == "stale"

    @patch("app.data.reader._query_collection")
    def test_freshness_fresh_when_recent(self, mock_query):
        from datetime import datetime, timezone, timedelta
        from app.utils.time_utils import now_utc

        recent_time = (now_utc() - timedelta(hours=1)).isoformat()
        mock_query.return_value = [{"updated_at": recent_time}]

        from app.data.reader import check_freshness
        result = check_freshness("CN", "000001", "basic_info")  # 24h 阈值
        assert result == "fresh"

    @patch("app.data.reader._query_collection")
    def test_freshness_stale_when_old(self, mock_query):
        from datetime import datetime, timezone, timedelta
        from app.utils.time_utils import now_utc

        old_time = (now_utc() - timedelta(hours=48)).isoformat()
        mock_query.return_value = [{"updated_at": old_time}]

        from app.data.reader import check_freshness
        result = check_freshness("CN", "000001", "basic_info")  # 24h 阈值
        assert result == "stale"

    @patch("app.data.reader._query_collection")
    def test_freshness_unknown_on_bad_timestamp(self, mock_query):
        mock_query.return_value = [{"updated_at": "not-a-date"}]
        from app.data.reader import check_freshness
        result = check_freshness("CN", "000001", "basic_info")
        assert result == "unknown"

    def test_hk_default_24h(self):
        """HK/US 市场使用默认 24h 阈值"""
        from app.data.reader import check_freshness
        # 无数据的 HK 股票应为 stale
        with patch("app.data.reader._query_collection", return_value=[]):
            result = check_freshness("HK", "00700", "daily_quotes")
            assert result == "stale"
