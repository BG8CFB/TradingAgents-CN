"""
按功能点组织的后端 API 端点测试

功能点：分析任务管理
覆盖路由：POST /api/analysis/single, GET /api/analysis/tasks 等
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from app.routers.analysis import router as analysis_router
from app.routers.auth_db import get_current_user


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


# ============================================================
# 功能点：提交分析任务
# ============================================================

class TestSubmitAnalysisFeature:
    """POST /api/analysis/single - 提交单股分析"""

    @pytest.mark.asyncio
    async def test_submit_without_auth(self):
        """未认证提交应返回 401"""
        app_no_auth = FastAPI()
        app_no_auth.include_router(analysis_router)
        transport = ASGITransport(app=app_no_auth)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            resp = await ac.post("/api/analysis/single", json={
                "stock_code": "000001",
            })
        assert resp.status_code in (401, 403)


# ============================================================
# 功能点：搜索股票
# ============================================================

class TestStockSearchFeature:
    """GET /api/analysis/search - 搜索股票"""

    @pytest.mark.asyncio
    async def test_search_without_auth(self):
        """未认证搜索应返回 401"""
        app_no_auth = FastAPI()
        app_no_auth.include_router(analysis_router)
        transport = ASGITransport(app=app_no_auth)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            resp = await ac.get("/api/analysis/search", params={"query": "平安"})
        assert resp.status_code in (401, 403)
