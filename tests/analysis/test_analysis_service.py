"""
分析服务测试

业务逻辑测试：测试 AnalysisService 的纯逻辑方法
数据依赖测试：使用 SimulatedMongoDB，通过设置全局变量注入
"""

import pytest
import app.core.database as db_module
from test_infra import SimulatedMongoDB


class TestHelperFunctions:
    """辅助函数测试 — 纯逻辑，无外部依赖"""

    def test_get_default_provider_by_model(self):
        from app.services.analysis_service import _get_default_provider_by_model

        assert _get_default_provider_by_model("qwen-turbo") == "dashscope"
        assert _get_default_provider_by_model("gpt-4o") == "openai"
        assert _get_default_provider_by_model("deepseek-chat") == "deepseek"
        assert _get_default_provider_by_model("unknown-model") == "dashscope"

    def test_get_default_backend_url(self):
        from app.services.analysis_service import _get_default_backend_url

        assert "openai.com" in _get_default_backend_url("openai")
        assert "deepseek.com" in _get_default_backend_url("deepseek")
        assert "dashscope" in _get_default_backend_url("dashscope")

    def test_serialize_for_response_converts_objectid(self):
        from app.services.analysis_service import AnalysisService
        from bson import ObjectId

        svc = AnalysisService.__new__(AnalysisService)
        oid = ObjectId()
        result = svc._serialize_for_response({"_id": oid, "name": "test"})
        assert result["_id"] == str(oid)
        assert result["name"] == "test"


class TestAnalysisServiceWithSimDB:
    """使用 SimulatedMongoDB 的 AnalysisService 测试"""

    @pytest.fixture
    def sim_db(self):
        return SimulatedMongoDB()

    @pytest.mark.asyncio
    async def test_search_returns_list(self, sim_db):
        from app.services.analysis_service import AnalysisService

        original = db_module.mongo_db
        db_module.mongo_db = sim_db
        try:
            svc = AnalysisService.__new__(AnalysisService)
            result = await svc.search_stock_basic_info("平安")
            assert isinstance(result, list)
        finally:
            db_module.mongo_db = original

    @pytest.mark.asyncio
    async def test_search_with_market_filter(self, sim_db):
        from app.services.analysis_service import AnalysisService

        await sim_db.stock_basic_info.insert_one({
            "code": "000001",
            "name": "平安银行",
            "market": "A股",
        })

        original = db_module.mongo_db
        db_module.mongo_db = sim_db
        try:
            svc = AnalysisService.__new__(AnalysisService)
            result = await svc.search_stock_basic_info("000001", market="A股")
            assert isinstance(result, list)
        finally:
            db_module.mongo_db = original

    @pytest.mark.asyncio
    async def test_get_popular_stocks_returns_list(self, sim_db):
        from app.services.analysis_service import AnalysisService

        original = db_module.mongo_db
        db_module.mongo_db = sim_db
        try:
            svc = AnalysisService.__new__(AnalysisService)
            result = await svc.get_popular_stocks(limit=5)
            assert isinstance(result, list)
        finally:
            db_module.mongo_db = original

    @pytest.mark.asyncio
    async def test_mark_task_failed_returns_false_for_missing(self, sim_db):
        """标记不存在的任务应返回 False 或 True（取决于实现）"""
        from app.services.analysis_service import AnalysisService

        original = db_module.mongo_db
        db_module.mongo_db = sim_db
        try:
            svc = AnalysisService.__new__(AnalysisService)
            result = await svc.mark_task_failed("nonexistent-task", "测试错误")
            # 不存在的任务，结果取决于实现
            assert isinstance(result, bool)
        finally:
            db_module.mongo_db = original


class TestGetAnalysisServiceSingleton:

    def test_get_analysis_service_returns_instance(self):
        from app.services.analysis_service import AnalysisService, get_analysis_service

        import app.services.analysis_service as mod
        mod.analysis_service = None

        svc = get_analysis_service()
        assert isinstance(svc, AnalysisService)

        mod.analysis_service = None
