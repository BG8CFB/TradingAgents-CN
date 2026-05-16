"""
测试 Redis 客户端模块

使用 SimulatedRedis 进行测试，不依赖真实 Redis 连接
"""

import json
import pytest

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


class TestGetRedisService:
    def test_returns_redis_service_instance(self):
        svc = get_redis_service()
        assert isinstance(svc, RedisService)
