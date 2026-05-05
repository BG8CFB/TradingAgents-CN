"""
测试 app/core/database.py — 数据库连接管理模块

仅 mock 外部依赖（Motor MongoDB、Redis），测试内部逻辑。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from app.core.database import (
    DatabaseManager,
    get_mongo_db,
    get_redis_client,
    get_mongo_client,
    get_database,
    init_database_views_and_indexes,
    db_manager,
)


class TestDatabaseManagerInit:
    """测试 DatabaseManager 初始化"""

    def test_init_sets_all_to_none(self):
        """初始化时所有连接和健康标志为 None/False"""
        mgr = DatabaseManager()
        assert mgr.mongo_client is None
        assert mgr.mongo_db is None
        assert mgr.redis_client is None
        assert mgr.redis_pool is None
        assert mgr._mongo_healthy is False
        assert mgr._redis_healthy is False


class TestDatabaseManagerHealthCheck:
    """测试 DatabaseManager.health_check()"""

    @pytest.mark.asyncio
    async def test_health_check_disconnected_when_no_clients(self):
        """无客户端时返回 disconnected 状态"""
        mgr = DatabaseManager()
        result = await mgr.health_check()

        assert result["mongodb"]["status"] == "disconnected"
        assert result["redis"]["status"] == "disconnected"

    @pytest.mark.asyncio
    async def test_health_check_healthy_mongodb(self):
        """MongoDB 连接健康时返回 healthy"""
        mgr = DatabaseManager()

        # mock MongoDB 客户端
        mock_client = AsyncMock()
        mock_client.admin.command = AsyncMock(return_value={"ok": 1})
        mgr.mongo_client = mock_client

        result = await mgr.health_check()
        assert result["mongodb"]["status"] == "healthy"
        assert result["mongodb"]["details"]["ping"] == {"ok": 1}
        assert mgr._mongo_healthy is True

    @pytest.mark.asyncio
    async def test_health_check_unhealthy_mongodb(self):
        """MongoDB 连接异常时返回 unhealthy"""
        mgr = DatabaseManager()

        mock_client = AsyncMock()
        mock_client.admin.command = AsyncMock(
            side_effect=Exception("connection refused")
        )
        mgr.mongo_client = mock_client

        result = await mgr.health_check()
        assert result["mongodb"]["status"] == "unhealthy"
        assert "connection refused" in result["mongodb"]["details"]["error"]
        assert mgr._mongo_healthy is False

    @pytest.mark.asyncio
    async def test_health_check_healthy_redis(self):
        """Redis 连接健康时返回 healthy"""
        mgr = DatabaseManager()

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mgr.redis_client = mock_redis

        result = await mgr.health_check()
        assert result["redis"]["status"] == "healthy"
        assert mgr._redis_healthy is True

    @pytest.mark.asyncio
    async def test_health_check_unhealthy_redis(self):
        """Redis 连接异常时返回 unhealthy"""
        mgr = DatabaseManager()

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(
            side_effect=Exception("redis connection error")
        )
        mgr.redis_client = mock_redis

        result = await mgr.health_check()
        assert result["redis"]["status"] == "unhealthy"
        assert "redis connection error" in result["redis"]["details"]["error"]
        assert mgr._redis_healthy is False

    @pytest.mark.asyncio
    async def test_health_check_returns_correct_structure(self):
        """health_check 返回正确的结构"""
        mgr = DatabaseManager()
        result = await mgr.health_check()

        assert "mongodb" in result
        assert "redis" in result
        assert "status" in result["mongodb"]
        assert "status" in result["redis"]


class TestDatabaseManagerIsHealthy:
    """测试 DatabaseManager.is_healthy 属性"""

    def test_is_healthy_false_when_both_unhealthy(self):
        """两个连接都不健康时返回 False"""
        mgr = DatabaseManager()
        mgr._mongo_healthy = False
        mgr._redis_healthy = False
        assert mgr.is_healthy is False

    def test_is_healthy_false_when_one_unhealthy(self):
        """一个连接不健康时返回 False"""
        mgr = DatabaseManager()
        mgr._mongo_healthy = True
        mgr._redis_healthy = False
        assert mgr.is_healthy is False

    def test_is_healthy_true_when_both_healthy(self):
        """两个连接都健康时返回 True"""
        mgr = DatabaseManager()
        mgr._mongo_healthy = True
        mgr._redis_healthy = True
        assert mgr.is_healthy is True


class TestGetMongoDB:
    """测试 get_mongo_db() 函数"""

    def test_raises_runtime_error_when_not_initialized(self):
        """未初始化时抛出 RuntimeError"""
        import app.core.database as db_module

        original = db_module.mongo_db
        db_module.mongo_db = None
        try:
            with pytest.raises(RuntimeError, match="MongoDB数据库未初始化"):
                get_mongo_db()
        finally:
            db_module.mongo_db = original

    def test_returns_db_when_initialized(self):
        """已初始化时返回数据库实例"""
        import app.core.database as db_module

        mock_db = MagicMock()
        original = db_module.mongo_db
        db_module.mongo_db = mock_db
        try:
            result = get_mongo_db()
            assert result is mock_db
        finally:
            db_module.mongo_db = original


class TestGetMongoClient:
    """测试 get_mongo_client() 函数"""

    def test_raises_runtime_error_when_not_initialized(self):
        """未初始化时抛出 RuntimeError"""
        import app.core.database as db_module

        original = db_module.mongo_client
        db_module.mongo_client = None
        try:
            with pytest.raises(RuntimeError, match="MongoDB客户端未初始化"):
                get_mongo_client()
        finally:
            db_module.mongo_client = original


class TestGetRedisClient:
    """测试 get_redis_client() 函数"""

    def test_raises_runtime_error_when_not_initialized(self):
        """未初始化时抛出 RuntimeError"""
        import app.core.database as db_module

        original = db_module.redis_client
        db_module.redis_client = None
        try:
            with pytest.raises(RuntimeError, match="Redis客户端未初始化"):
                get_redis_client()
        finally:
            db_module.redis_client = original

    def test_returns_client_when_initialized(self):
        """已初始化时返回客户端实例"""
        import app.core.database as db_module

        mock_redis = MagicMock()
        original = db_module.redis_client
        db_module.redis_client = mock_redis
        try:
            result = get_redis_client()
            assert result is mock_redis
        finally:
            db_module.redis_client = original


class TestGetDatabase:
    """测试 get_database() 函数"""

    def test_raises_runtime_error_when_not_initialized(self):
        """未初始化时抛出 RuntimeError"""
        import app.core.database as db_module

        original_client = db_module.db_manager.mongo_client
        db_module.db_manager.mongo_client = None
        try:
            with pytest.raises(RuntimeError, match="MongoDB客户端未初始化"):
                get_database()
        finally:
            db_module.db_manager.mongo_client = original_client


class TestInitDatabaseViewsAndIndexes:
    """测试 init_database_views_and_indexes() 错误处理"""

    @pytest.mark.asyncio
    async def test_handles_error_gracefully(self):
        """初始化失败时不抛出异常"""
        with patch("app.core.database.get_mongo_db", side_effect=RuntimeError("not init")):
            # 应该不抛出异常，仅记录警告
            await init_database_views_and_indexes()


class TestDatabaseManagerCloseConnections:
    """测试 DatabaseManager.close_connections()"""

    @pytest.mark.asyncio
    async def test_close_with_no_connections(self):
        """无连接时正常关闭"""
        mgr = DatabaseManager()
        # 不应抛出异常
        await mgr.close_connections()
        assert mgr._mongo_healthy is False
        assert mgr._redis_healthy is False

    @pytest.mark.asyncio
    async def test_close_mongo_connection(self):
        """关闭 MongoDB 连接"""
        mgr = DatabaseManager()
        mock_client = MagicMock()
        mock_client.close = MagicMock()
        mgr.mongo_client = mock_client
        mgr._mongo_healthy = True

        await mgr.close_connections()
        mock_client.close.assert_called_once()
        assert mgr._mongo_healthy is False

    @pytest.mark.asyncio
    async def test_close_redis_connection(self):
        """关闭 Redis 连接"""
        mgr = DatabaseManager()
        mock_redis = AsyncMock()
        mock_redis.close = AsyncMock()
        mock_pool = AsyncMock()
        mock_pool.disconnect = AsyncMock()
        mgr.redis_client = mock_redis
        mgr.redis_pool = mock_pool
        mgr._redis_healthy = True

        await mgr.close_connections()
        mock_redis.close.assert_called_once()
        mock_pool.disconnect.assert_called_once()
        assert mgr._redis_healthy is False

    @pytest.mark.asyncio
    async def test_close_handles_redis_error(self):
        """关闭 Redis 时出错不影响整体流程"""
        mgr = DatabaseManager()
        mock_redis = AsyncMock()
        mock_redis.close = AsyncMock(side_effect=Exception("close error"))
        mgr.redis_client = mock_redis
        mgr._redis_healthy = True

        # 不应抛出异常——close_connections 捕获了异常
        await mgr.close_connections()
        # 注意：源码中如果 redis_client.close() 抛出异常，
        # _redis_healthy = False 不会被执行（它在 close 之后），
        # 但流程应该正常完成而不崩溃
        assert mgr._redis_healthy is True  # 保持原值，未被修改


class TestGlobalDbManager:
    """测试全局 db_manager 实例"""

    def test_global_db_manager_exists(self):
        """全局 db_manager 已创建"""
        assert db_manager is not None
        assert isinstance(db_manager, DatabaseManager)
