"""DataRefreshService 锁与冷却期单元测试"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.cn_data_refresh_service import DataRefreshService, RefreshResult


class TestCooldown:
    """冷却期测试"""

    def test_cooldown_blocks_refresh(self):
        service = DataRefreshService.__new__(DataRefreshService)
        service._cooldown_seconds = 300
        service._cooldowns = {}

        # 首次不冷却
        assert not service._is_in_cooldown("000001", "daily_quotes")

        # 标记刷新后冷却
        service._mark_refreshed("000001", "daily_quotes")
        assert service._is_in_cooldown("000001", "daily_quotes")

    def test_cooldown_per_symbol_domain(self):
        service = DataRefreshService.__new__(DataRefreshService)
        service._cooldown_seconds = 300
        service._cooldowns = {}

        service._mark_refreshed("000001", "daily_quotes")
        assert service._is_in_cooldown("000001", "daily_quotes")
        assert not service._is_in_cooldown("000001", "financial")
        assert not service._is_in_cooldown("600036", "daily_quotes")


class TestLockMechanism:
    """锁机制测试"""

    def test_lock_isolation(self):
        """不同 symbol:domain 使用不同锁"""
        service = DataRefreshService.__new__(DataRefreshService)
        service._locks = {}

        lock1 = service._get_lock("000001", "daily_quotes")
        lock2 = service._get_lock("000001", "financial")
        lock3 = service._get_lock("600036", "daily_quotes")

        assert lock1 is not lock2
        assert lock1 is not lock3
        assert lock2 is not lock3

    def test_lock_reuse(self):
        """同一 key 复用锁"""
        service = DataRefreshService.__new__(DataRefreshService)
        service._locks = {}

        lock1 = service._get_lock("000001", "daily_quotes")
        lock2 = service._get_lock("000001", "daily_quotes")

        assert lock1 is lock2


class TestAggregateStatus:
    """状态汇总测试"""

    def test_all_fresh(self):
        from app.services.cn_data_refresh_service import DomainRefreshResult

        result = RefreshResult(symbol="000001")
        result.domains = {
            "daily_quotes": DomainRefreshResult(domain="daily_quotes", status="fresh"),
            "financial": DomainRefreshResult(domain="financial", status="fresh"),
        }

        assert DataRefreshService._aggregate_status(result.domains) == "fresh"

    def test_all_refreshed(self):
        from app.services.cn_data_refresh_service import DomainRefreshResult

        result = RefreshResult(symbol="000001")
        result.domains = {
            "daily_quotes": DomainRefreshResult(domain="daily_quotes", status="refreshed"),
            "financial": DomainRefreshResult(domain="financial", status="refreshed"),
        }

        assert DataRefreshService._aggregate_status(result.domains) == "refreshed"

    def test_mixed_success_and_failure(self):
        from app.services.cn_data_refresh_service import DomainRefreshResult

        result = RefreshResult(symbol="000001")
        result.domains = {
            "daily_quotes": DomainRefreshResult(domain="daily_quotes", status="refreshed"),
            "financial": DomainRefreshResult(domain="financial", status="failed", error="源不可用"),
        }

        assert DataRefreshService._aggregate_status(result.domains) == "partial"

    def test_all_failed(self):
        from app.services.cn_data_refresh_service import DomainRefreshResult

        result = RefreshResult(symbol="000001")
        result.domains = {
            "daily_quotes": DomainRefreshResult(domain="daily_quotes", status="failed", error="err"),
            "financial": DomainRefreshResult(domain="financial", status="timeout", error="timeout"),
        }

        assert DataRefreshService._aggregate_status(result.domains) == "failed"
