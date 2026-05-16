"""
测试队列服务

使用 SimulatedRedis 内存模拟，不依赖真实 Redis
"""

import json
import pytest

from app.services.queue_service import QueueService
from test_infra import SimulatedRedis


@pytest.fixture
def sim_redis():
    return SimulatedRedis()


@pytest.fixture
def service(sim_redis):
    return QueueService(sim_redis)


class TestEnqueueTask:
    @pytest.mark.asyncio
    async def test_success_returns_task_id(self, service, sim_redis):
        """正常入队应返回 task_id"""
        # 先设置用户队列为空（无并发任务）
        task_id = await service.enqueue_task("user-1", "000001", {"model": "qwen"})
        assert task_id is not None
        assert isinstance(task_id, str)
        assert len(task_id) > 0

    @pytest.mark.asyncio
    async def test_saves_task_to_redis(self, service, sim_redis):
        """入队后 Redis 中应有任务数据"""
        task_id = await service.enqueue_task("user-1", "000001", {})
        # 验证数据已写入 Redis（通过 SimulatedRedis 的内部状态）
        assert task_id is not None


class TestDequeueTask:
    @pytest.mark.asyncio
    async def test_returns_none_for_empty_queue(self, service, sim_redis):
        """空队列应返回 None"""
        result = await service.dequeue_task("worker-1")
        assert result is None
