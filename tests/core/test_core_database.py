"""
测试 app/core/database.py — 数据库连接管理模块

使用 SimulatedMongoDB/SimulatedRedis 进行测试
需要真实数据库连接的测试标记 @pytest.mark.requires_db
"""

import asyncio
import pytest

from app.core.database import (
    DatabaseManager,
    get_mongo_db,
    get_redis_client,
    get_mongo_client,
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
        mgr = DatabaseManager()
        mgr._mongo_healthy = False
        mgr._redis_healthy = False
        assert mgr.is_healthy is False

    def test_is_healthy_false_when_one_unhealthy(self):
        mgr = DatabaseManager()
        mgr._mongo_healthy = True
        mgr._redis_healthy = False
        assert mgr.is_healthy is False

    def test_is_healthy_true_when_both_healthy(self):
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


class TestGetMongoClient:
    """测试 get_mongo_client() 函数"""

    def test_raises_runtime_error_when_not_initialized(self):
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
        import app.core.database as db_module

        original = db_module.redis_client
        db_module.redis_client = None
        try:
            with pytest.raises(RuntimeError, match="Redis客户端未初始化"):
                get_redis_client()
        finally:
            db_module.redis_client = original


class TestGetMongoDB:
    """测试 get_mongo_db() 函数"""

    def test_raises_runtime_error_when_not_initialized(self):
        import app.core.database as db_module

        original_db = db_module.mongo_db
        db_module.mongo_db = None
        try:
            with pytest.raises(RuntimeError, match="MongoDB数据库未初始化"):
                get_mongo_db()
        finally:
            db_module.mongo_db = original_db


class TestInitDatabaseViewsAndIndexes:
    """测试 init_database_views_and_indexes() 错误处理"""

    @pytest.mark.asyncio
    async def test_handles_error_gracefully(self):
        """初始化失败时不抛出异常"""
        import app.core.database as db_module
        original = db_module.mongo_db
        db_module.mongo_db = None
        try:
            await init_database_views_and_indexes()
        finally:
            db_module.mongo_db = original


class TestDatabaseManagerCloseConnections:
    """测试 DatabaseManager.close_connections()"""

    @pytest.mark.asyncio
    async def test_close_with_no_connections(self):
        mgr = DatabaseManager()
        await mgr.close_connections()
        assert mgr._mongo_healthy is False
        assert mgr._redis_healthy is False


class TestGlobalDbManager:
    """测试全局 db_manager 实例"""

    def test_global_db_manager_exists(self):
        assert db_manager is not None
        assert isinstance(db_manager, DatabaseManager)
