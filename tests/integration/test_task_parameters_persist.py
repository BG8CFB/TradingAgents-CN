"""单股任务创建 parameters 落库集成测试（真实 MongoDB，无 mock）

覆盖：create_analysis_task 后 analysis_tasks 文档内 parameters 完整落库
（对齐批量链路 insert_many 行为），get_task_overview 返回值与落库一致。
"""

from datetime import datetime

import pytest

from app.models.analysis import AnalysisParameters, SingleAnalysisRequest
from app.services.analysis_service import get_analysis_service

TEST_USER_ID = "507f1f77bcf86cd799439011"


@pytest.fixture(autouse=True)
async def _real_mongo(mongodb_available):
    """每用例重建真实 MongoDB 客户端（motor 客户端绑定事件循环，
    pytest-asyncio 每用例新循环，必须重新初始化避免跨循环游标错误）"""
    import app.core.database as db_mod
    from app.core.database import close_database, init_database

    await init_database()
    yield
    await close_database()
    db_mod.mongo_db = None
    db_mod.mongo_client = None


@pytest.mark.requires_db
class TestTaskParametersPersist:
    async def test_parameters_persisted_in_mongodb(self):
        """创建任务后直接查 analysis_tasks 文档，parameters 完整落库"""
        from app.core.database import get_mongo_db

        svc = get_analysis_service()
        params = AnalysisParameters(
            market_type="A股",
            analysis_date=datetime(2024, 12, 31),
            selected_analysts=["market_analyst", "fundamentals_analyst"],
            language="中文",
            phase2_enabled=True,
            phase2_debate_rounds=3,
            phase3_enabled=True,
            phase3_debate_rounds=2,
        )
        req = SingleAnalysisRequest(symbol="000001", parameters=params)
        created = await svc.create_analysis_task(TEST_USER_ID, req)
        task_id = created["task_id"]
        db = get_mongo_db()
        try:
            doc = await db.analysis_tasks.find_one({"task_id": task_id})
            assert doc is not None, "任务文档必须已写入 analysis_tasks"
            persisted = doc.get("parameters")
            assert isinstance(persisted, dict), f"parameters 应为 dict，实际: {persisted!r}"
            assert persisted["market_type"] == "A股"
            assert persisted["selected_analysts"] == [
                "market_analyst",
                "fundamentals_analyst",
            ]
            assert persisted["phase2_enabled"] is True
            assert persisted["phase2_debate_rounds"] == 3
            assert persisted["phase3_enabled"] is True
            assert persisted["phase3_debate_rounds"] == 2
        finally:
            await db.analysis_tasks.delete_many({"task_id": task_id})
            await svc.memory_manager.remove_task(task_id)

    async def test_overview_parameters_match_persisted(self):
        """get_task_overview 返回的 parameters 与落库文档一致"""
        from app.core.database import get_mongo_db

        svc = get_analysis_service()
        params = AnalysisParameters(
            market_type="港股",
            selected_analysts=["news_analyst"],
            phase2_enabled=True,
            phase2_debate_rounds=1,
            phase3_enabled=False,
        )
        req = SingleAnalysisRequest(symbol="00700", parameters=params)
        created = await svc.create_analysis_task(TEST_USER_ID, req)
        task_id = created["task_id"]
        db = get_mongo_db()
        try:
            doc = await db.analysis_tasks.find_one({"task_id": task_id})
            assert doc is not None
            overview = await svc.get_task_overview(task_id, user_id=TEST_USER_ID)
            assert overview is not None
            assert overview["parameters"] == doc["parameters"]
            assert overview["parameters"]["selected_analysts"] == ["news_analyst"]
            assert overview["market_type"] == "港股"
        finally:
            await db.analysis_tasks.delete_many({"task_id": task_id})
            await svc.memory_manager.remove_task(task_id)

    async def test_empty_parameters_persisted_as_empty_dict(self):
        """无 parameters 时也写入空 dict（与内存任务行为一致）"""
        from app.core.database import get_mongo_db

        svc = get_analysis_service()
        req = SingleAnalysisRequest(symbol="000002")
        created = await svc.create_analysis_task(TEST_USER_ID, req)
        task_id = created["task_id"]
        db = get_mongo_db()
        try:
            doc = await db.analysis_tasks.find_one({"task_id": task_id})
            assert doc is not None
            assert doc.get("parameters") == {}
        finally:
            await db.analysis_tasks.delete_many({"task_id": task_id})
            await svc.memory_manager.remove_task(task_id)
