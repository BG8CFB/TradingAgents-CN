"""测试 FallbackRouter — 重试逻辑、降级记录。"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.data.processor.circuit_breaker import CircuitBreaker
from app.data.processor.rate_limiter import RateLimiter
from app.data.processor.fallback_router import FallbackRouter, FetchResult


class TestFetchResult:
    def test_init(self):
        r = FetchResult()
        assert r.success is False
        assert r.records == []
        assert r.source is None
        assert r.error is None

    def test_with_data(self):
        r = FetchResult()
        r.success = True
        r.records = [{"symbol": "000001"}]
        r.source = "tushare"
        assert r.success is True
        assert len(r.records) == 1


class TestFallbackRouter:
    def test_init(self):
        registry = MagicMock()
        priority = MagicMock()
        router = FallbackRouter(registry, priority)
        assert router._circuit is not None
        assert router._rate_limiter is not None

    @pytest.mark.asyncio
    async def test_no_sources(self):
        registry = MagicMock()
        registry.get_ordered_sources.return_value = []
        priority = MagicMock()
        priority.get_priority = AsyncMock(return_value=[])
        router = FallbackRouter(registry, priority)

        result = await router.fetch("CN", "daily_quotes", "000001")
        assert result.success is False
        assert "无可用数据源" in result.error
