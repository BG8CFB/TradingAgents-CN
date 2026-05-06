"""测试队列服务"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.queue_service import QueueService


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.hset = AsyncMock()
    redis.lpush = AsyncMock()
    redis.rpop = AsyncMock(return_value=None)
    redis.sadd = AsyncMock()
    redis.scard = AsyncMock(return_value=0)
    redis.hgetall = AsyncMock(return_value={})
    return redis


@pytest.fixture
def service(mock_redis):
    return QueueService(mock_redis)


class TestEnqueueTask:
    @pytest.mark.asyncio
    @patch("app.services.queue_service.check_user_concurrent_limit", new_callable=AsyncMock, return_value=True)
    @patch("app.services.queue_service.check_global_concurrent_limit", new_callable=AsyncMock, return_value=True)
    async def test_success_returns_task_id(self, mock_global, mock_user, service, mock_redis):
        task_id = await service.enqueue_task("user-1", "000001", {"model": "qwen"})
        assert task_id is not None
        assert isinstance(task_id, str)
        assert len(task_id) > 0

    @pytest.mark.asyncio
    @patch("app.services.queue_service.check_user_concurrent_limit", new_callable=AsyncMock, return_value=True)
    @patch("app.services.queue_service.check_global_concurrent_limit", new_callable=AsyncMock, return_value=True)
    async def test_saves_task_to_redis(self, mock_global, mock_user, service, mock_redis):
        task_id = await service.enqueue_task("user-1", "000001", {})
        mock_redis.hset.assert_called_once()
        mock_redis.lpush.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.services.queue_service.check_user_concurrent_limit", new_callable=AsyncMock, return_value=False)
    async def test_raises_on_user_limit(self, mock_user, service):
        with pytest.raises(ValueError, match="并发限制"):
            await service.enqueue_task("user-1", "000001", {})

    @pytest.mark.asyncio
    @patch("app.services.queue_service.check_user_concurrent_limit", new_callable=AsyncMock, return_value=True)
    @patch("app.services.queue_service.check_global_concurrent_limit", new_callable=AsyncMock, return_value=False)
    async def test_raises_on_global_limit(self, mock_global, mock_user, service):
        with pytest.raises(ValueError, match="全局并发限制"):
            await service.enqueue_task("user-1", "000001", {})


class TestDequeueTask:
    @pytest.mark.asyncio
    async def test_returns_none_for_empty_queue(self, service, mock_redis):
        mock_redis.rpop.return_value = None
        result = await service.dequeue_task("worker-1")
        assert result is None
