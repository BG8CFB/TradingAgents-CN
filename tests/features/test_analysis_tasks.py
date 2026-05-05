"""
按功能点组织的后端 API 端点测试

功能点：分析任务管理
覆盖路由：POST /api/analysis/single, GET /api/analysis/tasks 等
运行：python -m pytest tests/features/test_analysis_tasks.py -v
"""

import pytest
import pytest_asyncio
from unittest.mock import patch, AsyncMock
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from app.routers.analysis import router as analysis_router
from app.routers.auth_db import get_current_user


# ============================================================
# 测试基础设施
# ============================================================

MOCK_USER = {
    "id": "507f1f77bcf86cd799439011",
    "username": "admin",
    "email": "admin@test.com",
    "name": "admin",
    "is_admin": True,
    "roles": ["admin"],
    "preferences": {},
}


def _make_analysis_app():
    """创建包含 analysis 路由的测试应用，并覆盖认证依赖"""
    app = FastAPI()
    app.include_router(analysis_router)
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    return app


@pytest.fixture
def analysis_app():
    return _make_analysis_app()


@pytest_asyncio.fixture
async def analysis_client(analysis_app):
    transport = ASGITransport(app=analysis_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


def _mock_analysis_service():
    """创建模拟的 AnalysisService 实例"""
    svc = AsyncMock()
    svc.create_analysis_task = AsyncMock(return_value={
        "task_id": "task-001",
        "status": "pending",
    })
    svc.list_user_tasks = AsyncMock(return_value=[])
    svc.list_all_tasks = AsyncMock(return_value=[])
    svc.get_task_with_status_fallback = AsyncMock(return_value={
        "task_id": "task-001",
        "status": "completed",
        "progress": 100,
    })
    svc.get_analysis_stats = AsyncMock(return_value={
        "total_tasks": 0,
        "completed": 0,
        "failed": 0,
        "pending": 0,
    })
    svc.search_stock_basic_info = AsyncMock(return_value=[])
    return svc


# ============================================================
# 功能点：提交分析任务
# ============================================================

class TestSubmitAnalysisFeature:
    """POST /api/analysis/single - 提交单股分析"""

    @pytest.mark.asyncio
    async def test_submit_analysis_success(self, analysis_client):
        """正常提交应返回 task_id"""
        mock_svc = _mock_analysis_service()

        with patch("app.services.analysis_service.get_analysis_service", return_value=mock_svc):
            resp = await analysis_client.post("/api/analysis/single", json={
                "stock_code": "000001",
                "analysis_date": "2024-12-31",
            })

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["task_id"] == "task-001"

    @pytest.mark.asyncio
    async def test_submit_without_auth(self, analysis_client):
        """未认证提交应返回 401（取消依赖覆盖后测试）"""
        app_no_auth = FastAPI()
        app_no_auth.include_router(analysis_router)
        transport = ASGITransport(app=app_no_auth)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            resp = await ac.post("/api/analysis/single", json={
                "stock_code": "000001",
            })
        assert resp.status_code in (401, 403)


# ============================================================
# 功能点：查询任务列表
# ============================================================

class TestListTasksFeature:
    """GET /api/analysis/tasks - 查询任务列表"""

    @pytest.mark.asyncio
    async def test_list_user_tasks_success(self, analysis_client):
        """认证用户应能查看自己的任务"""
        mock_svc = _mock_analysis_service()

        with patch("app.services.analysis_service.get_analysis_service", return_value=mock_svc):
            resp = await analysis_client.get("/api/analysis/tasks")

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "tasks" in body["data"]

    @pytest.mark.asyncio
    async def test_list_all_tasks(self, analysis_client):
        """管理员应能查看所有任务"""
        mock_svc = _mock_analysis_service()

        with patch("app.services.analysis_service.get_analysis_service", return_value=mock_svc):
            resp = await analysis_client.get("/api/analysis/tasks/all")

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True


# ============================================================
# 功能点：查询任务状态
# ============================================================

class TestTaskStatusFeature:
    """GET /api/analysis/tasks/{task_id}/status - 查询任务状态"""

    @pytest.mark.asyncio
    async def test_get_task_status(self, analysis_client):
        """应返回任务状态"""
        mock_svc = _mock_analysis_service()

        with patch("app.services.analysis_service.get_analysis_service", return_value=mock_svc):
            resp = await analysis_client.get("/api/analysis/tasks/task-001/status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["task_id"] == "task-001"
        assert body["data"]["status"] == "completed"


# ============================================================
# 功能点：搜索股票
# ============================================================

class TestStockSearchFeature:
    """GET /api/analysis/search - 搜索股票"""

    @pytest.mark.asyncio
    async def test_search_stocks(self, analysis_client):
        """搜索股票应返回结果"""
        mock_svc = _mock_analysis_service()
        mock_svc.search_stock_basic_info = AsyncMock(return_value=[
            {"stock_code": "000001", "stock_name": "平安银行"}
        ])

        with patch("app.services.analysis_service.get_analysis_service", return_value=mock_svc):
            resp = await analysis_client.get(
                "/api/analysis/search",
                params={"query": "平安"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert len(body["data"]) == 1


# ============================================================
# 功能点：分析统计
# ============================================================

class TestAnalysisStatsFeature:
    """GET /api/analysis/stats - 分析统计"""

    @pytest.mark.asyncio
    async def test_get_stats(self, analysis_client):
        """应返回统计数据"""
        mock_svc = _mock_analysis_service()

        with patch("app.services.analysis_service.get_analysis_service", return_value=mock_svc):
            resp = await analysis_client.get("/api/analysis/stats")

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "data" in body
