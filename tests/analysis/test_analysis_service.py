"""
分析服务单元测试
测试 AnalysisService 的核心方法（使用 mock DB）
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# Helpers: 创建 mock 依赖
# ---------------------------------------------------------------------------

def _make_mock_db():
    """创建模拟的 MongoDB 数据库"""
    db = AsyncMock()
    db.analysis_tasks = AsyncMock()
    db.analysis_tasks.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
    db.analysis_tasks.find_one = AsyncMock(return_value=None)
    db.analysis_tasks.find = MagicMock()
    db.analysis_tasks.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
    db.analysis_tasks.count_documents = AsyncMock(return_value=0)
    db.analysis_reports = AsyncMock()
    db.analysis_reports.find_one = AsyncMock(return_value=None)
    db.analysis_reports.aggregate = MagicMock()
    db.analysis_reports.insert_one = AsyncMock(return_value=MagicMock(inserted_id="mock_id"))
    db.analysis_reports.count_documents = AsyncMock(return_value=0)
    db.stock_basic_info = AsyncMock()
    db.stock_basic_info.find_one = AsyncMock(return_value=None)
    db.stock_basic_info.find = MagicMock()
    db.market_quotes = AsyncMock()
    db.market_quotes.find_one = AsyncMock(return_value=None)
    return db


def _make_mock_memory_manager():
    """创建模拟的内存状态管理器"""
    mgr = AsyncMock()
    mgr.create_task = AsyncMock()
    mgr.update_task_status = AsyncMock()
    mgr.get_task_dict = AsyncMock(return_value=None)
    mgr.list_all_tasks = AsyncMock(return_value=[])
    mgr.list_user_tasks = AsyncMock(return_value=[])
    mgr.remove_task = AsyncMock()
    mgr.cleanup_zombie_tasks = AsyncMock(return_value={"total_cleaned": 0})
    mgr.set_websocket_manager = MagicMock()
    return mgr


def _make_mock_request(stock_code: str = "000001"):
    """创建模拟的 SingleAnalysisRequest"""
    req = MagicMock()
    req.stock_code = stock_code
    req.get_symbol = MagicMock(return_value=stock_code)
    req.parameters = MagicMock()
    req.parameters.model_dump = MagicMock(return_value={})
    req.parameters.selected_analysts = ["market_analyst"]
    req.parameters.market_type = "A股"
    req.parameters.analysis_date = None
    req.parameters.quick_analysis_model = "qwen-turbo"
    req.parameters.deep_analysis_model = "qwen-max"
    req.parameters.research_depth = None
    return req


# ---------------------------------------------------------------------------
# Test Classes
# ---------------------------------------------------------------------------

class TestAnalysisServiceCreateTask:
    """AnalysisService.create_analysis_task 测试"""

    @pytest.mark.asyncio
    async def test_create_task_returns_task_id(self):
        """创建任务应返回 task_id"""
        from app.services.analysis_service import AnalysisService

        mock_db = _make_mock_db()
        mock_mgr = _make_mock_memory_manager()

        with patch("app.services.analysis_service.get_mongo_db", return_value=mock_db), \
             patch("app.services.analysis_service.get_memory_state_manager", return_value=mock_mgr), \
             patch("app.services.analysis_service.get_redis_client"), \
             patch("app.services.analysis_service.get_websocket_manager"), \
             patch("app.services.analysis_service.QueueService"), \
             patch("app.services.analysis_service.UsageStatisticsService"):
            svc = AnalysisService()
            svc.memory_manager = mock_mgr

            request = _make_mock_request("000001")
            result = await svc.create_analysis_task("user-123", request)

        assert "task_id" in result
        assert isinstance(result["task_id"], str)
        assert len(result["task_id"]) > 0

    @pytest.mark.asyncio
    async def test_create_task_returns_pending_status(self):
        """创建任务应返回 pending 状态"""
        from app.services.analysis_service import AnalysisService

        mock_db = _make_mock_db()
        mock_mgr = _make_mock_memory_manager()

        with patch("app.services.analysis_service.get_mongo_db", return_value=mock_db), \
             patch("app.services.analysis_service.get_memory_state_manager", return_value=mock_mgr), \
             patch("app.services.analysis_service.get_redis_client"), \
             patch("app.services.analysis_service.get_websocket_manager"), \
             patch("app.services.analysis_service.QueueService"), \
             patch("app.services.analysis_service.UsageStatisticsService"):
            svc = AnalysisService()
            svc.memory_manager = mock_mgr

            request = _make_mock_request("600519")
            result = await svc.create_analysis_task("user-123", request)

        assert result["status"] == "pending"

    @pytest.mark.asyncio
    async def test_create_task_calls_memory_manager(self):
        """创建任务应调用内存管理器的 create_task"""
        from app.services.analysis_service import AnalysisService

        mock_db = _make_mock_db()
        mock_mgr = _make_mock_memory_manager()

        with patch("app.services.analysis_service.get_mongo_db", return_value=mock_db), \
             patch("app.services.analysis_service.get_memory_state_manager", return_value=mock_mgr), \
             patch("app.services.analysis_service.get_redis_client"), \
             patch("app.services.analysis_service.get_websocket_manager"), \
             patch("app.services.analysis_service.QueueService"), \
             patch("app.services.analysis_service.UsageStatisticsService"):
            svc = AnalysisService()
            svc.memory_manager = mock_mgr

            request = _make_mock_request("000001")
            await svc.create_analysis_task("user-123", request)

        mock_mgr.create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_task_writes_to_mongodb(self):
        """创建任务应写入 MongoDB"""
        from app.services.analysis_service import AnalysisService

        mock_db = _make_mock_db()
        mock_mgr = _make_mock_memory_manager()

        with patch("app.services.analysis_service.get_mongo_db", return_value=mock_db), \
             patch("app.services.analysis_service.get_memory_state_manager", return_value=mock_mgr), \
             patch("app.services.analysis_service.get_redis_client"), \
             patch("app.services.analysis_service.get_websocket_manager"), \
             patch("app.services.analysis_service.QueueService"), \
             patch("app.services.analysis_service.UsageStatisticsService"):
            svc = AnalysisService()
            svc.memory_manager = mock_mgr

            request = _make_mock_request("000001")
            await svc.create_analysis_task("user-123", request)

        mock_db.analysis_tasks.update_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_task_raises_on_empty_symbol(self):
        """空股票代码应抛出异常"""
        from app.services.analysis_service import AnalysisService

        mock_db = _make_mock_db()
        mock_mgr = _make_mock_memory_manager()

        with patch("app.services.analysis_service.get_mongo_db", return_value=mock_db), \
             patch("app.services.analysis_service.get_memory_state_manager", return_value=mock_mgr), \
             patch("app.services.analysis_service.get_redis_client"), \
             patch("app.services.analysis_service.get_websocket_manager"), \
             patch("app.services.analysis_service.QueueService"), \
             patch("app.services.analysis_service.UsageStatisticsService"):
            svc = AnalysisService()
            svc.memory_manager = mock_mgr

            request = _make_mock_request("")
            request.get_symbol = MagicMock(return_value="")

            with pytest.raises(Exception):
                await svc.create_analysis_task("user-123", request)


class TestAnalysisServiceListTasks:
    """AnalysisService.list_all_tasks / list_user_tasks 测试"""

    @pytest.mark.asyncio
    async def test_list_all_tasks_returns_list(self):
        """list_all_tasks 应返回列表"""
        from app.services.analysis_service import AnalysisService

        mock_db = _make_mock_db()
        mock_mgr = _make_mock_memory_manager()

        # 模拟 find cursor
        mock_cursor = AsyncMock()
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_cursor.skip = MagicMock(return_value=mock_cursor)
        mock_cursor.limit = MagicMock(return_value=mock_cursor)
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_db.analysis_tasks.find = MagicMock(return_value=mock_cursor)

        with patch("app.services.analysis_service.get_mongo_db", return_value=mock_db), \
             patch("app.services.analysis_service.get_memory_state_manager", return_value=mock_mgr), \
             patch("app.services.analysis_service.get_redis_client"), \
             patch("app.services.analysis_service.get_websocket_manager"), \
             patch("app.services.analysis_service.QueueService"), \
             patch("app.services.analysis_service.UsageStatisticsService"):
            svc = AnalysisService()
            svc.memory_manager = mock_mgr
            result = await svc.list_all_tasks()

        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_list_user_tasks_filters_by_user(self):
        """list_user_tasks 应按用户 ID 过滤"""
        from app.services.analysis_service import AnalysisService

        mock_db = _make_mock_db()
        mock_mgr = _make_mock_memory_manager()

        mock_cursor = AsyncMock()
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_cursor.skip = MagicMock(return_value=mock_cursor)
        mock_cursor.limit = MagicMock(return_value=mock_cursor)
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_db.analysis_tasks.find = MagicMock(return_value=mock_cursor)

        with patch("app.services.analysis_service.get_mongo_db", return_value=mock_db), \
             patch("app.services.analysis_service.get_memory_state_manager", return_value=mock_mgr), \
             patch("app.services.analysis_service.get_redis_client"), \
             patch("app.services.analysis_service.get_websocket_manager"), \
             patch("app.services.analysis_service.QueueService"), \
             patch("app.services.analysis_service.UsageStatisticsService"):
            svc = AnalysisService()
            svc.memory_manager = mock_mgr
            result = await svc.list_user_tasks("user-123")

        assert isinstance(result, list)
        # 验证 find 被调用时包含 user_id 过滤
        find_args = mock_db.analysis_tasks.find.call_args[0][0]
        assert find_args["user_id"] == "user-123"

    @pytest.mark.asyncio
    async def test_list_all_tasks_with_status_filter(self):
        """list_all_tasks 支持状态过滤"""
        from app.services.analysis_service import AnalysisService

        mock_db = _make_mock_db()
        mock_mgr = _make_mock_memory_manager()

        mock_cursor = AsyncMock()
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_cursor.skip = MagicMock(return_value=mock_cursor)
        mock_cursor.limit = MagicMock(return_value=mock_cursor)
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_db.analysis_tasks.find = MagicMock(return_value=mock_cursor)

        with patch("app.services.analysis_service.get_mongo_db", return_value=mock_db), \
             patch("app.services.analysis_service.get_memory_state_manager", return_value=mock_mgr), \
             patch("app.services.analysis_service.get_redis_client"), \
             patch("app.services.analysis_service.get_websocket_manager"), \
             patch("app.services.analysis_service.QueueService"), \
             patch("app.services.analysis_service.UsageStatisticsService"):
            svc = AnalysisService()
            svc.memory_manager = mock_mgr
            result = await svc.list_all_tasks(status="completed")

        find_args = mock_db.analysis_tasks.find.call_args[0][0]
        assert find_args["status"] == "completed"

    @pytest.mark.asyncio
    async def test_list_all_tasks_converts_processing_to_running(self):
        """processing 状态应被转换为 running"""
        from app.services.analysis_service import AnalysisService

        mock_db = _make_mock_db()
        mock_mgr = _make_mock_memory_manager()

        mock_cursor = AsyncMock()
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_cursor.skip = MagicMock(return_value=mock_cursor)
        mock_cursor.limit = MagicMock(return_value=mock_cursor)
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_db.analysis_tasks.find = MagicMock(return_value=mock_cursor)

        with patch("app.services.analysis_service.get_mongo_db", return_value=mock_db), \
             patch("app.services.analysis_service.get_memory_state_manager", return_value=mock_mgr), \
             patch("app.services.analysis_service.get_redis_client"), \
             patch("app.services.analysis_service.get_websocket_manager"), \
             patch("app.services.analysis_service.QueueService"), \
             patch("app.services.analysis_service.UsageStatisticsService"):
            svc = AnalysisService()
            svc.memory_manager = mock_mgr
            await svc.list_all_tasks(status="processing")

        find_args = mock_db.analysis_tasks.find.call_args[0][0]
        assert find_args["status"] == "running"


class TestAnalysisServiceSearchStocks:
    """AnalysisService.search_stock_basic_info 测试"""

    @pytest.mark.asyncio
    async def test_search_returns_list(self):
        """搜索股票应返回列表"""
        from app.services.analysis_service import AnalysisService

        mock_db = _make_mock_db()
        mock_mgr = _make_mock_memory_manager()

        # 模拟 find cursor (async iterator)
        mock_cursor = MagicMock()
        mock_cursor.limit = MagicMock(return_value=mock_cursor)
        mock_cursor.__aiter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__anext__ = AsyncMock(side_effect=StopAsyncIteration)
        mock_db.stock_basic_info.find = MagicMock(return_value=mock_cursor)

        with patch("app.services.analysis_service.get_mongo_db", return_value=mock_db), \
             patch("app.services.analysis_service.get_memory_state_manager", return_value=mock_mgr), \
             patch("app.services.analysis_service.get_redis_client"), \
             patch("app.services.analysis_service.get_websocket_manager"), \
             patch("app.services.analysis_service.QueueService"), \
             patch("app.services.analysis_service.UsageStatisticsService"):
            svc = AnalysisService()
            svc.memory_manager = mock_mgr
            result = await svc.search_stock_basic_info("平安")

        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_search_with_market_filter(self):
        """搜索股票支持市场过滤"""
        from app.services.analysis_service import AnalysisService

        mock_db = _make_mock_db()
        mock_mgr = _make_mock_memory_manager()

        mock_cursor = MagicMock()
        mock_cursor.limit = MagicMock(return_value=mock_cursor)
        mock_cursor.__aiter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__anext__ = AsyncMock(side_effect=StopAsyncIteration)
        mock_db.stock_basic_info.find = MagicMock(return_value=mock_cursor)

        with patch("app.services.analysis_service.get_mongo_db", return_value=mock_db), \
             patch("app.services.analysis_service.get_memory_state_manager", return_value=mock_mgr), \
             patch("app.services.analysis_service.get_redis_client"), \
             patch("app.services.analysis_service.get_websocket_manager"), \
             patch("app.services.analysis_service.QueueService"), \
             patch("app.services.analysis_service.UsageStatisticsService"):
            svc = AnalysisService()
            svc.memory_manager = mock_mgr
            await svc.search_stock_basic_info("000001", market="A股")

        find_args = mock_db.stock_basic_info.find.call_args[0][0]
        assert find_args["market"] == "A股"


class TestAnalysisServicePopularStocks:
    """AnalysisService.get_popular_stocks 测试"""

    @pytest.mark.asyncio
    async def test_get_popular_stocks_returns_list(self):
        """获取热门股票应返回列表"""
        from app.services.analysis_service import AnalysisService

        mock_db = _make_mock_db()
        mock_mgr = _make_mock_memory_manager()

        # 模拟聚合管道返回的 async iterator
        mock_agg = MagicMock()
        mock_agg.__aiter__ = MagicMock(return_value=mock_agg)
        mock_agg.__anext__ = AsyncMock(side_effect=StopAsyncIteration)
        mock_db.analysis_reports.aggregate = MagicMock(return_value=mock_agg)

        with patch("app.services.analysis_service.get_mongo_db", return_value=mock_db), \
             patch("app.services.analysis_service.get_memory_state_manager", return_value=mock_mgr), \
             patch("app.services.analysis_service.get_redis_client"), \
             patch("app.services.analysis_service.get_websocket_manager"), \
             patch("app.services.analysis_service.QueueService"), \
             patch("app.services.analysis_service.UsageStatisticsService"):
            svc = AnalysisService()
            svc.memory_manager = mock_mgr
            result = await svc.get_popular_stocks(limit=5)

        assert isinstance(result, list)


class TestAnalysisServiceTaskStatus:
    """AnalysisService.get_task_status 测试"""

    @pytest.mark.asyncio
    async def test_get_task_status_returns_none_for_unknown(self):
        """未知任务应返回 None"""
        from app.services.analysis_service import AnalysisService

        mock_mgr = _make_mock_memory_manager()
        mock_mgr.get_task_dict = AsyncMock(return_value=None)

        with patch("app.services.analysis_service.get_mongo_db", return_value=_make_mock_db()), \
             patch("app.services.analysis_service.get_memory_state_manager", return_value=mock_mgr), \
             patch("app.services.analysis_service.get_redis_client"), \
             patch("app.services.analysis_service.get_websocket_manager"), \
             patch("app.services.analysis_service.QueueService"), \
             patch("app.services.analysis_service.UsageStatisticsService"), \
             patch("app.services.analysis_service.get_progress_by_id", return_value=None):
            svc = AnalysisService()
            svc.memory_manager = mock_mgr
            result = await svc.get_task_status("nonexistent-task-id")

        assert result is None


class TestAnalysisServiceMarkFailed:
    """AnalysisService.mark_task_failed 测试"""

    @pytest.mark.asyncio
    async def test_mark_task_failed_updates_db(self):
        """标记失败应更新 MongoDB"""
        from app.services.analysis_service import AnalysisService

        mock_db = _make_mock_db()
        mock_mgr = _make_mock_memory_manager()

        with patch("app.services.analysis_service.get_mongo_db", return_value=mock_db), \
             patch("app.services.analysis_service.get_memory_state_manager", return_value=mock_mgr), \
             patch("app.services.analysis_service.get_redis_client"), \
             patch("app.services.analysis_service.get_websocket_manager"), \
             patch("app.services.analysis_service.QueueService"), \
             patch("app.services.analysis_service.UsageStatisticsService"):
            svc = AnalysisService()
            svc.memory_manager = mock_mgr
            result = await svc.mark_task_failed("task-123", "测试错误")

        assert result is True
        mock_db.analysis_tasks.update_one.assert_called_once()
        mock_mgr.update_task_status.assert_called_once()


class TestAnalysisServiceDeleteTask:
    """AnalysisService.delete_task_by_id 测试"""

    @pytest.mark.asyncio
    async def test_delete_task_removes_from_memory_and_db(self):
        """删除任务应同时删除内存和数据库记录"""
        from app.services.analysis_service import AnalysisService

        mock_db = _make_mock_db()
        mock_mgr = _make_mock_memory_manager()

        with patch("app.services.analysis_service.get_mongo_db", return_value=mock_db), \
             patch("app.services.analysis_service.get_memory_state_manager", return_value=mock_mgr), \
             patch("app.services.analysis_service.get_redis_client"), \
             patch("app.services.analysis_service.get_websocket_manager"), \
             patch("app.services.analysis_service.QueueService"), \
             patch("app.services.analysis_service.UsageStatisticsService"):
            svc = AnalysisService()
            svc.memory_manager = mock_mgr
            result = await svc.delete_task_by_id("task-123")

        assert result is True
        mock_mgr.remove_task.assert_called_once_with("task-123")
        mock_db.analysis_tasks.delete_one.assert_called_once()


class TestGetAnalysisServiceSingleton:
    """get_analysis_service 单例测试"""

    def test_get_analysis_service_returns_instance(self):
        """get_analysis_service 应返回 AnalysisService 实例"""
        from app.services.analysis_service import AnalysisService, get_analysis_service

        with patch("app.services.analysis_service.get_memory_state_manager", return_value=_make_mock_memory_manager()), \
             patch("app.services.analysis_service.get_redis_client"), \
             patch("app.services.analysis_service.get_websocket_manager"), \
             patch("app.services.analysis_service.QueueService"), \
             patch("app.services.analysis_service.UsageStatisticsService"):
            # 重置全局单例
            import app.services.analysis_service as mod
            mod.analysis_service = None
            svc = get_analysis_service()

        assert isinstance(svc, AnalysisService)
        # 清理
        mod.analysis_service = None


class TestHelperFunctions:
    """辅助函数测试"""

    def test_get_default_provider_by_model(self):
        """默认供应商映射应正确"""
        from app.services.analysis_service import _get_default_provider_by_model

        assert _get_default_provider_by_model("qwen-turbo") == "dashscope"
        assert _get_default_provider_by_model("gpt-4o") == "openai"
        assert _get_default_provider_by_model("deepseek-chat") == "deepseek"
        assert _get_default_provider_by_model("unknown-model") == "dashscope"  # 默认

    def test_get_default_backend_url(self):
        """默认后端 URL 映射应正确"""
        from app.services.analysis_service import _get_default_backend_url

        assert "openai.com" in _get_default_backend_url("openai")
        assert "deepseek.com" in _get_default_backend_url("deepseek")
        assert "dashscope" in _get_default_backend_url("dashscope")

    def test_serialize_for_response_converts_objectid(self):
        """ObjectId 序列化应转为字符串"""
        from app.services.analysis_service import AnalysisService
        from bson import ObjectId

        with patch("app.services.analysis_service.get_memory_state_manager", return_value=_make_mock_memory_manager()), \
             patch("app.services.analysis_service.get_redis_client"), \
             patch("app.services.analysis_service.get_websocket_manager"), \
             patch("app.services.analysis_service.QueueService"), \
             patch("app.services.analysis_service.UsageStatisticsService"):
            svc = AnalysisService.__new__(AnalysisService)

        oid = ObjectId()
        result = svc._serialize_for_response({"_id": oid, "name": "test"})
        assert result["_id"] == str(oid)
        assert result["name"] == "test"
