"""
测试基础设施 - 全局 fixtures 和配置

设计原则：
- 调用实际代码函数，不使用 MagicMock/patch 替代被测逻辑
- DB/Redis 使用 SimulatedMongoDB/SimulatedRedis（内存实现），连接不可用时优雅降级
- LLM 测试拆分为：业务逻辑测试（无 LLM 调用）和 LLM 集成测试（真实 API）
"""

import asyncio
import os
import sys
import warnings
from typing import AsyncGenerator, Generator

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


# ============================================================
# DB/Redis 可用性检测与模拟数据 Fixtures
# ============================================================

def _check_mongodb_available() -> bool:
    """检测 MongoDB 是否可用"""
    try:
        import pymongo
        client = pymongo.MongoClient(
            os.environ.get("MONGODB_HOST", "localhost"),
            int(os.environ.get("MONGODB_PORT", "27017")),
            username=os.environ.get("MONGODB_USERNAME", "admin"),
            password=os.environ.get("MONGODB_PASSWORD", "tradingagents123"),
            serverSelectionTimeoutMS=2000,
        )
        client.admin.command("ping")
        client.close()
        return True
    except Exception:
        return False


def _check_redis_available() -> bool:
    """检测 Redis 是否可用"""
    try:
        import redis
        r = redis.Redis(
            host=os.environ.get("REDIS_HOST", "localhost"),
            port=int(os.environ.get("REDIS_PORT", "6379")),
            password=os.environ.get("REDIS_PASSWORD", "tradingagents123"),
            socket_timeout=2,
        )
        r.ping()
        r.close()
        return True
    except Exception:
        return False


# 缓存可用性检测结果（session 级别）
_MONGODB_AVAILABLE = None
_REDIS_AVAILABLE = None


def is_mongodb_available() -> bool:
    global _MONGODB_AVAILABLE
    if _MONGODB_AVAILABLE is None:
        _MONGODB_AVAILABLE = _check_mongodb_available()
    return _MONGODB_AVAILABLE


def is_redis_available() -> bool:
    global _REDIS_AVAILABLE
    if _REDIS_AVAILABLE is None:
        _REDIS_AVAILABLE = _check_redis_available()
    return _REDIS_AVAILABLE


@pytest.fixture
def mongodb_available():
    """MongoDB 可用性 fixture，不可用时跳过测试"""
    if not is_mongodb_available():
        pytest.skip("MongoDB 不可用，跳过数据库相关测试")
    return True


@pytest.fixture
def redis_available():
    """Redis 可用性 fixture，不可用时跳过测试"""
    if not is_redis_available():
        pytest.skip("Redis 不可用，跳过 Redis 相关测试")
    return True


# ============================================================
# 模拟数据 Fixtures（真实数据结构，非 MagicMock）
# ============================================================

import importlib
import os as _os
_sys_path_test = _os.path.dirname(_os.path.abspath(__file__))
if _sys_path_test not in sys.path:
    sys.path.insert(0, _sys_path_test)
from test_infra import SimulatedMongoDB, SimulatedRedis


@pytest.fixture
def sim_db():
    """创建内存模拟的 MongoDB 数据库"""
    return SimulatedMongoDB()


@pytest.fixture
def sim_redis():
    """创建内存模拟的 Redis 客户端"""
    return SimulatedRedis()


@pytest.fixture
def inject_sim_db(sim_db):
    """将 SimulatedMongoDB 注入到 app.data.storage.mongo.client._motor_db。

    直接替换全局 _motor_db 变量，使所有通过 get_motor_db() 获取数据库的代码
    走内存模拟，而不是连接真实 MongoDB。
    """
    from app.data.storage.mongo import client as mongo_client

    original = mongo_client._motor_db
    mongo_client._motor_db = sim_db
    yield sim_db
    mongo_client._motor_db = original


# ============================================================
# Auth Fixtures
# ============================================================

@pytest.fixture
def auth_service():
    """获取 AuthService 类"""
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
def admin_user_data():
    """管理员用户测试数据"""
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
def normal_user_data():
    """普通用户测试数据"""
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

@pytest_asyncio.fixture
async def client():
    """创建测试 HTTP 客户端（直接使用实际 app，跳过 lifespan）"""
    from app.main import app
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
async def authed_client(client, admin_token, admin_user_data):
    """带认证的测试客户端"""
    from app.routers.auth_db import get_current_user

    async def override_get_current_user():
        return admin_user_data

    from app.main import app
    app.dependency_overrides[get_current_user] = override_get_current_user
    client.headers.update({"Authorization": f"Bearer {admin_token}"})
    yield client
    app.dependency_overrides.pop(get_current_user, None)


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
# Engine 测试数据 Fixtures
# ============================================================

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
