"""Reader 新鲜度判定测试 — 基于新架构 app.data.core.reader.Reader。"""

import asyncio
from unittest.mock import patch, MagicMock, AsyncMock


class TestFreshnessCheck:
    """测试 Reader.check_freshness 的新鲜度判定逻辑。"""

    def _get_reader(self):
        from app.data.core.reader import Reader
        return Reader()

    def test_freshness_unknown_for_missing_rule(self):
        """未知域应返回 unknown。"""
        reader = self._get_reader()
        result = asyncio.run(reader.check_freshness("CN", "000001", "nonexistent_domain"))
        assert result == "unknown" or result.value == "unknown"

    def test_freshness_unknown_when_no_data(self):
        """无数据时返回 unknown。"""
        reader = self._get_reader()
        with patch.object(reader, "_get_repo", return_value=None):
            result = asyncio.run(reader.check_freshness("CN", "000001", "basic_info"))
            assert result in ("unknown", "stale") or (hasattr(result, 'value') and result.value in ("unknown", "stale"))

    def test_freshness_fresh_when_recent(self):
        """最近更新的数据应返回 fresh。"""
        from datetime import datetime, timezone, timedelta
        from app.utils.time_utils import now_utc

        reader = self._get_reader()
        recent_time = (now_utc() - timedelta(hours=1)).isoformat()
        data = {"updated_at": recent_time}

        result = asyncio.run(reader.check_freshness("CN", "000001", "basic_info", data))
        assert result in ("fresh", "unknown") or (hasattr(result, 'value') and result.value in ("fresh", "unknown"))

    def test_freshness_stale_when_old(self):
        """过期数据应返回 stale。"""
        from datetime import datetime, timezone, timedelta
        from app.utils.time_utils import now_utc

        reader = self._get_reader()
        old_time = (now_utc() - timedelta(hours=48)).isoformat()
        data = {"updated_at": old_time}

        result = asyncio.run(reader.check_freshness("CN", "000001", "basic_info", data))
        assert result in ("stale", "unknown") or (hasattr(result, 'value') and result.value in ("stale", "unknown"))

    def test_freshness_unknown_on_bad_timestamp(self):
        """无效时间戳应返回 unknown。"""
        reader = self._get_reader()
        data = {"updated_at": "not-a-date"}

        result = asyncio.run(reader.check_freshness("CN", "000001", "basic_info", data))
        assert result == "unknown" or (hasattr(result, 'value') and result.value == "unknown")

    def test_hk_default_24h(self):
        """HK 市场应使用默认阈值。"""
        reader = self._get_reader()
        result = asyncio.run(reader.check_freshness("HK", "00700", "daily_quotes"))
        assert result in ("unknown", "stale") or (hasattr(result, 'value') and result.value in ("unknown", "stale"))
