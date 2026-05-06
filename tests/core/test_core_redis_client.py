"""测试 Redis 客户端模块"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.redis_client import RedisKeys, RedisService, get_redis_service


class TestRedisKeys:
    def test_queue_keys_contain_placeholders(self):
        assert "{user_id}" in RedisKeys.USER_PENDING_QUEUE
        assert "{task_id}" in RedisKeys.TASK_PROGRESS
        assert "{batch_id}" in RedisKeys.BATCH_PROGRESS
        assert "{session_id}" in RedisKeys.USER_SESSION
        assert "{cache_key}" in RedisKeys.SCREENING_CACHE

    def test_static_keys_present(self):
        assert RedisKeys.GLOBAL_PENDING_QUEUE == "global:pending"
        assert RedisKeys.QUEUE_STATS == "queue:stats"
        assert RedisKeys.SYSTEM_CONFIG == "system:config"

    def test_all_expected_keys_exist(self):
        expected = [
            "USER_PENDING_QUEUE", "USER_PROCESSING_SET",
            "GLOBAL_PENDING_QUEUE", "GLOBAL_PROCESSING_SET",
            "TASK_PROGRESS", "TASK_RESULT", "TASK_LOCK",
            "BATCH_PROGRESS", "BATCH_TASKS", "BATCH_LOCK",
            "USER_SESSION", "USER_RATE_LIMIT", "USER_DAILY_QUOTA",
            "QUEUE_STATS", "SYSTEM_CONFIG", "WORKER_HEARTBEAT",
            "SCREENING_CACHE", "ANALYSIS_CACHE",
        ]
        for key in expected:
            assert hasattr(RedisKeys, key)


class TestRedisService:
    @pytest.fixture
    def service(self):
        return RedisService()

    @pytest.fixture
    def mock_redis(self):
        redis = AsyncMock()
        redis.setex = AsyncMock(return_value=True)
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock(return_value=True)
        redis.eval = AsyncMock(return_value=1)
        redis.lpush = AsyncMock(return_value=1)
        redis.brpop = AsyncMock(return_value=None)
        redis.llen = AsyncMock(return_value=0)
        redis.sadd = AsyncMock(return_value=1)
        redis.srem = AsyncMock(return_value=1)
        redis.sismember = AsyncMock(return_value=0)
        redis.scard = AsyncMock(return_value=0)
        return redis

    def _patch_get_redis(self, mock_redis):
        return patch("app.core.redis_client.get_redis", return_value=mock_redis)

    @pytest.mark.asyncio
    async def test_set_with_ttl(self, service, mock_redis):
        with self._patch_get_redis(mock_redis):
            await service.set_with_ttl("key1", "value1", ttl=3600)
            mock_redis.setex.assert_called_once_with("key1", 3600, "value1")

    @pytest.mark.asyncio
    async def test_get_json_returns_parsed(self, service, mock_redis):
        mock_redis.get.return_value = json.dumps({"a": 1})
        with self._patch_get_redis(mock_redis):
            result = await service.get_json("key1")
            assert result == {"a": 1}

    @pytest.mark.asyncio
    async def test_get_json_returns_none_for_missing(self, service, mock_redis):
        mock_redis.get.return_value = None
        with self._patch_get_redis(mock_redis):
            result = await service.get_json("key1")
            assert result is None

    @pytest.mark.asyncio
    async def test_set_json_with_ttl(self, service, mock_redis):
        with self._patch_get_redis(mock_redis):
            await service.set_json("key1", {"b": 2}, ttl=600)
            mock_redis.setex.assert_called_once()
            call_args = mock_redis.setex.call_args
            assert call_args[0][0] == "key1"
            assert call_args[0][1] == 600

    @pytest.mark.asyncio
    async def test_set_json_without_ttl(self, service, mock_redis):
        with self._patch_get_redis(mock_redis):
            await service.set_json("key1", {"b": 2})
            mock_redis.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_increment_with_ttl(self, service, mock_redis):
        mock_redis.eval.return_value = 5
        with self._patch_get_redis(mock_redis):
            result = await service.increment_with_ttl("counter", ttl=300)
            assert result == 5
            mock_redis.eval.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_to_queue(self, service, mock_redis):
        with self._patch_get_redis(mock_redis):
            await service.add_to_queue("queue_key", {"task": "data"})
            mock_redis.lpush.assert_called_once()

    @pytest.mark.asyncio
    async def test_pop_from_queue_with_data(self, service, mock_redis):
        mock_redis.brpop.return_value = ("queue_key", json.dumps({"task": "data"}))
        with self._patch_get_redis(mock_redis):
            result = await service.pop_from_queue("queue_key")
            assert result == {"task": "data"}

    @pytest.mark.asyncio
    async def test_pop_from_queue_empty(self, service, mock_redis):
        mock_redis.brpop.return_value = None
        with self._patch_get_redis(mock_redis):
            result = await service.pop_from_queue("queue_key")
            assert result is None

    @pytest.mark.asyncio
    async def test_get_queue_length(self, service, mock_redis):
        mock_redis.llen.return_value = 10
        with self._patch_get_redis(mock_redis):
            result = await service.get_queue_length("queue_key")
            assert result == 10

    @pytest.mark.asyncio
    async def test_add_to_set(self, service, mock_redis):
        with self._patch_get_redis(mock_redis):
            await service.add_to_set("set_key", "member1")
            mock_redis.sadd.assert_called_once_with("set_key", "member1")

    @pytest.mark.asyncio
    async def test_remove_from_set(self, service, mock_redis):
        with self._patch_get_redis(mock_redis):
            await service.remove_from_set("set_key", "member1")
            mock_redis.srem.assert_called_once_with("set_key", "member1")

    @pytest.mark.asyncio
    async def test_is_in_set(self, service, mock_redis):
        mock_redis.sismember.return_value = 1
        with self._patch_get_redis(mock_redis):
            result = await service.is_in_set("set_key", "member1")
            assert result == 1

    @pytest.mark.asyncio
    async def test_get_set_size(self, service, mock_redis):
        mock_redis.scard.return_value = 5
        with self._patch_get_redis(mock_redis):
            result = await service.get_set_size("set_key")
            assert result == 5

    @pytest.mark.asyncio
    async def test_acquire_lock_success(self, service, mock_redis):
        mock_redis.set.return_value = True
        with self._patch_get_redis(mock_redis):
            lock_value = await service.acquire_lock("lock_key", timeout=30)
            assert lock_value is not None

    @pytest.mark.asyncio
    async def test_acquire_lock_failure(self, service, mock_redis):
        mock_redis.set.return_value = None
        with self._patch_get_redis(mock_redis):
            lock_value = await service.acquire_lock("lock_key")
            assert lock_value is None

    @pytest.mark.asyncio
    async def test_extend_lock(self, service, mock_redis):
        mock_redis.eval.return_value = 1
        with self._patch_get_redis(mock_redis):
            result = await service.extend_lock("lock_key", "lock_value", 30)
            assert result is True

    @pytest.mark.asyncio
    async def test_release_lock(self, service, mock_redis):
        mock_redis.eval.return_value = 1
        with self._patch_get_redis(mock_redis):
            await service.release_lock("lock_key", "lock_value")
            mock_redis.eval.assert_called_once()


class TestGetRedisService:
    def test_returns_redis_service_instance(self):
        svc = get_redis_service()
        assert isinstance(svc, RedisService)
