"""GET /api/analysis/tasks/{task_id}/overview 集成测试（真实 MongoDB，无 mock）

覆盖：任务参数聚合返回、股票信息可缺失（stock_info=null 不报错）、
无权/不存在任务返回 404。
"""

import pytest

from app.models.analysis import AnalysisParameters, SingleAnalysisRequest
from app.services.analysis_service import get_analysis_service


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
class TestTaskOverviewAPI:
    async def test_overview_returns_task_and_optional_stock(self, authed_client):
        """真实创建任务后 GET overview：返回 task_id/symbol/market_type，stock_info 键存在"""
        from app.core.database import get_mongo_db

        svc = get_analysis_service()
        req = SingleAnalysisRequest(
            symbol="000001",
            parameters=AnalysisParameters(market_type="A股"),
        )
        admin_user_id = "507f1f77bcf86cd799439011"
        created = await svc.create_analysis_task(admin_user_id, req)
        task_id = created["task_id"]
        db = get_mongo_db()
        try:
            resp = await authed_client.get(f"/api/analysis/tasks/{task_id}/overview")
            assert resp.status_code == 200
            body = resp.json()
            assert body["success"] is True
            data = body["data"]
            assert data["task"]["task_id"] == task_id
            assert data["task"]["symbol"] == "000001"
            assert data["task"]["market_type"] == "A股"
            assert data["task"]["status"] == "pending"
            assert "stock_info" in data  # 测试库可能无 basic_info，允许 null
        finally:
            await db.analysis_tasks.delete_many({"task_id": task_id})
            await svc.memory_manager.remove_task(task_id)

    async def test_overview_404_for_other_user(self, user_client):
        """普通用户查询不存在的任务 → 404（不泄露存在性）"""
        resp = await user_client.get(
            "/api/analysis/tasks/nonexistent-task-id/overview"
        )
        assert resp.status_code == 404
