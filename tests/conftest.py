"""
测试基础设施 - 全局 fixtures 和配置
"""

import asyncio
import os
import sys
import warnings
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# 抑制配置模块的 deprecation warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*安全.*")
warnings.filterwarnings("ignore", message=".*Environment variable.*")

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 设置测试环境变量（在导入 app 模块之前）
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("MONGODB_HOST", "localhost")
os.environ.setdefault("MONGODB_PORT", "27017")
os.environ.setdefault("MONGODB_USERNAME", "admin")
os.environ.setdefault("MONGODB_PASSWORD", "tradingagents123")
os.environ.setdefault("MONGODB_DATABASE", "tradingagents_test")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")
os.environ.setdefault("REDIS_PASSWORD", "tradingagents123")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-testing-only")
os.environ.setdefault("CSRF_SECRET", "test-csrf-secret-for-testing-only")
os.environ.setdefault("MONGODB_ENABLED", "true")
os.environ.setdefault("REDIS_ENABLED", "true")


# ============================================================
# Event loop 配置
# ============================================================

@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """创建 session 级别的事件循环"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ============================================================
# 核心模块 Fixtures
# ============================================================

@pytest.fixture
def settings():
    """获取配置实例"""
    from app.core.config import get_settings
    return get_settings()


@pytest.fixture
def mock_mongo_db():
    """模拟 MongoDB 数据库实例"""
    db = AsyncMock()
    db.list_collection_names = AsyncMock(return_value=[])
    db.command = AsyncMock(return_value={"ok": 1})
    return db


@pytest.fixture
def mock_redis_client():
    """模拟 Redis 客户端"""
    client = AsyncMock()
    client.ping = AsyncMock(return_value=True)
    client.get = AsyncMock(return_value=None)
    client.set = AsyncMock(return_value=True)
    client.delete = AsyncMock(return_value=1)
    client.exists = AsyncMock(return_value=0)
    client.expire = AsyncMock(return_value=True)
    client.close = AsyncMock()
    return client


# ============================================================
# 数据库 patch fixtures（用于需要隔离数据库的场景）
# ============================================================

@pytest_asyncio.fixture
async def patched_db(mock_mongo_db, mock_redis_client):
    """Patch 数据库全局变量，让服务代码使用 mock 数据库"""
    with patch("app.core.database.mongo_db", mock_mongo_db), \
         patch("app.core.database.redis_client", mock_redis_client), \
         patch("app.core.database.get_mongo_db", return_value=mock_mongo_db), \
         patch("app.core.database.get_redis_client", return_value=mock_redis_client):
        yield mock_mongo_db, mock_redis_client


# ============================================================
# Auth Fixtures
# ============================================================

@pytest.fixture
def auth_service():
    """获取 AuthService 实例"""
    from app.services.auth_service import AuthService
    return AuthService


@pytest.fixture
def admin_token(auth_service):
    """生成管理员 JWT token"""
    return auth_service.create_access_token(sub="test_admin")


@pytest.fixture
def user_token(auth_service):
    """生成普通用户 JWT token"""
    return auth_service.create_access_token(sub="test_user")


@pytest.fixture
def admin_headers(admin_token):
    """管理员认证头"""
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def user_headers(user_token):
    """普通用户认证头"""
    return {"Authorization": f"Bearer {user_token}"}


@pytest.fixture
def mock_admin_user():
    """模拟管理员用户数据"""
    return {
        "id": "507f1f77bcf86cd799439011",
        "username": "test_admin",
        "email": "admin@test.com",
        "name": "test_admin",
        "is_admin": True,
        "roles": ["admin"],
        "preferences": {"language": "zh-CN", "ui_theme": "light"},
    }


@pytest.fixture
def mock_normal_user():
    """模拟普通用户数据"""
    return {
        "id": "507f1f77bcf86cd799439012",
        "username": "test_user",
        "email": "user@test.com",
        "name": "test_user",
        "is_admin": False,
        "roles": ["user"],
        "preferences": {"language": "zh-CN", "ui_theme": "light"},
    }


# ============================================================
# FastAPI Test Client
# ============================================================

def _create_test_app():
    """创建用于测试的 FastAPI 应用（不启动 lifespan）"""
    from fastapi import FastAPI
    from app.core.config import settings

    app = FastAPI(
        title="TradingAgents-CN Test API",
        version="1.1.0-preview",
    )

    # 添加 CORS
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    return app


@pytest_asyncio.fixture
async def client():
    """创建测试 HTTP 客户端（直接使用实际 app，跳过 lifespan）"""
    from app.main import app

    # Patch lifespan 为空上下文
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_lifespan(app):
        yield

    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = mock_lifespan

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    app.router.lifespan_context = original_lifespan


@pytest_asyncio.fixture
async def authed_client(client, admin_token, mock_admin_user):
    """带认证的测试客户端（mock 用户验证）"""
    from app.services.user_service import User

    mock_user = MagicMock()
    mock_user.id = MagicMock()
    mock_user.id.__str__ = lambda self: mock_admin_user["id"]
    mock_user.username = mock_admin_user["username"]
    mock_user.email = mock_admin_user["email"]
    mock_user.is_admin = mock_admin_user["is_admin"]
    mock_user.is_active = True
    mock_user.preferences = MagicMock()
    mock_user.preferences.model_dump = MagicMock(return_value=mock_admin_user["preferences"])

    with patch("app.routers.auth_db.user_service") as mock_us, \
         patch("app.services.operation_log_service.log_operation", new_callable=AsyncMock):
        mock_us.get_user_by_username = AsyncMock(return_value=mock_user)
        client._mock_user_service = mock_us
        client._mock_user = mock_user
        client.headers.update({"Authorization": f"Bearer {admin_token}"})
        yield client


# ============================================================
# 通用测试数据 Fixtures
# ============================================================

@pytest.fixture
def sample_stock_data():
    """示例股票数据"""
    return {
        "code": "000001",
        "name": "平安银行",
        "industry": "银行",
        "area": "深圳",
        "market": "A股",
        "pe": 5.23,
        "pb": 0.65,
        "total_mv": 250000000000,
        "circ_mv": 250000000000,
    }


@pytest.fixture
def sample_analysis_task():
    """示例分析任务数据"""
    return {
        "task_id": "test-task-001",
        "stock_code": "000001",
        "stock_name": "平安银行",
        "status": "pending",
        "created_at": "2024-01-01T00:00:00Z",
        "user_id": "507f1f77bcf86cd799439011",
    }


# ============================================================
# Engine 测试 Fixtures
# ============================================================

@pytest.fixture
def mock_llm():
    """模拟 LLM 实例，可配置返回内容"""
    llm = MagicMock()
    default_response = MagicMock()
    default_response.content = '{"action": "持有", "target_price": null, "confidence": 0.7, "risk_score": 0.5, "reasoning": "测试"}'
    llm.invoke = MagicMock(return_value=default_response)
    llm.bind_tools = MagicMock(return_value=llm)
    return llm


@pytest.fixture
def sample_agent_state():
    """预填充的 AgentState 字典"""
    return {
        "messages": [],
        "company_of_interest": "000001",
        "trade_date": "2024-12-31",
        "task_id": "test-task-001",
        "investment_debate_state": {
            "history": "",
            "current_response": "",
            "count": 0,
            "current_round_index": 0,
            "max_rounds": 2,
            "rounds": [],
            "bull_report_content": "",
            "bear_report_content": "",
            "bull_history": "看好市场",
            "bear_history": "看空市场",
            "judge_decision": "裁决结果",
        },
        "risk_debate_state": {
            "history": "",
            "current_risky_response": "",
            "current_safe_response": "",
            "current_neutral_response": "",
            "count": 0,
            "latest_speaker": "",
            "risky_history": "激进观点",
            "safe_history": "保守观点",
            "neutral_history": "中性观点",
            "judge_decision": "风控裁决",
            "rounds": [],
            "current_round_index": 0,
            "max_rounds": 3,
            "risky_report_content": "",
            "safe_report_content": "",
            "neutral_report_content": "",
        },
        "reports": {},
        "market_report": "市场报告内容",
        "fundamentals_report": "基本面报告内容",
    }


@pytest.fixture
def sample_yaml_config(tmp_path):
    """创建临时 YAML 配置文件"""
    import yaml
    config = {
        "customModes": [
            {
                "slug": "market-analyst",
                "name": "市场技术分析师",
                "roleDefinition": "你是一个市场技术分析专家",
                "tools": ["get_stock_data"],
            },
            {
                "slug": "fundamentals-analyst",
                "name": "基本面分析师",
                "roleDefinition": "你是一个基本面分析专家",
                "tools": ["get_stock_fundamentals"],
            },
        ],
        "agents": [
            {
                "slug": "news-analyst",
                "name": "新闻分析师",
                "roleDefinition": "你是一个新闻分析专家",
                "tools": ["get_stock_news"],
            },
        ],
    }
    config_path = tmp_path / "phase1_agents_config.yaml"
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True)
    return str(config_path)


@pytest.fixture
def mock_memory():
    """模拟 FinancialSituationMemory"""
    memory = MagicMock()
    memory.add_situations = MagicMock()
    memory.get_memories = MagicMock(return_value=[])
    return memory


# ============================================================
# Pytest 配置
# ============================================================

def pytest_configure(config):
    """pytest 配置"""
    config.addinivalue_line("markers", "asyncio: mark test as async")
    config.addinivalue_line("markers", "slow: mark test as slow")
    config.addinivalue_line("markers", "integration: mark test as integration test")
    config.addinivalue_line("markers", "requires_db: mark test as requiring database")
    config.addinivalue_line("markers", "ai: mark test as requiring AI API")
