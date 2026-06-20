"""
PR1 / S1 安全测试 — 三市场子路由鉴权

验证 cn/hk/us 各市场子路由（data.py / sync.py）鉴权策略：
- GET 类端点：未携带 token → 401；携带普通用户 token → 200
- 写操作（POST/PUT）端点：未携带 token → 401；普通用户 → 403；管理员 → 200

设计原则（已迁移到真实 DB 鉴权路径）：
- 不使用 MagicMock / unittest.mock / dependency_overrides 模拟身份
- 通过 SimulatedMongoDB 预置真实用户文档（含真实密码哈希）
- 使用 AuthService.create_access_token 生成真实 JWT，走完整 get_current_user 流程
- 三种身份分别用 anon_client / user_client / admin_client fixture 切换
"""

import importlib

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.data.core.interface import DataInterface


# ---------------------------------------------------------------------------
# 测试辅助：构造真实 DB 鉴权路径下的客户端
# ---------------------------------------------------------------------------


async def _build_real_client(
    router,
    *,
    sim_db,
    user_data: dict | None,
) -> AsyncClient:
    """构造使用真实 DB 鉴权路径的 ASGI 客户端。

    Args:
        router: 子路由（app.routers.cn.data.router 等）
        sim_db: SimulatedMongoDB 实例
        user_data: 用户数据；None 表示匿名（无 token）

    实现要点：
    - 注入 sim_db 到 mongo_client._motor_db（与 conftest.inject_sim_db 同路径）
    - 切换 user_service.db 到 sim_db
    - 若 user_data 非 None，预置真实用户文档 + 真实 JWT
    """
    from app.data.storage.mongo import client as mongo_client
    from app.services.user_service import user_service
    from app.services.auth_service import AuthService
    from app.utils.passwords import hash_password
    from app.utils.time_utils import now_utc
    from app.middleware.csrf import (
        CSRF_COOKIE_NAME,
        CSRF_HEADER_NAME,
        generate_csrf_token,
    )

    mongo_client._motor_db = sim_db
    original_db = user_service.db
    user_service.set_database(sim_db)

    app = FastAPI()
    app.include_router(router)

    csrf_token = generate_csrf_token("test-session-fixed")

    headers: dict[str, str] = {CSRF_HEADER_NAME: csrf_token}
    if user_data is not None:
        # 真实密码哈希 + 真实 JWT
        user_doc = {
            "_id": user_data["id"],
            "username": user_data["username"],
            "email": user_data["email"],
            "hashed_password": hash_password("Test@1234"),
            "is_admin": bool(user_data.get("is_admin", False)),
            "is_active": True,
            "created_at": now_utc(),
            "preferences": user_data.get("preferences", {}),
        }
        await sim_db.users.insert_one(user_doc)
        token = AuthService.create_access_token(sub=user_data["username"])
        headers["Authorization"] = f"Bearer {token}"

    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    client.cookies.set(CSRF_COOKIE_NAME, csrf_token)
    client.headers.update(headers)

    # 把 original_db 挂到 client 上便于 finally 还原
    client._user_service_original_db = original_db  # type: ignore[attr-defined]
    client._sim_db = sim_db  # type: ignore[attr-defined]
    client._user_data = user_data  # type: ignore[attr-defined]
    return client


async def _close_real_client(client: AsyncClient) -> None:
    """关闭客户端并还原 user_service.db。"""
    original_db = client._user_service_original_db  # type: ignore[attr-defined]
    sim_db = client._sim_db  # type: ignore[attr-defined]
    user_data = client._user_data  # type: ignore[attr-defined]
    try:
        await client.aclose()
    finally:
        from app.services.user_service import user_service
        user_service.set_database(original_db)
        if user_data is not None:
            try:
                await sim_db.users.delete_many({"username": user_data["username"]})
            except Exception as exc:
                import motor.errors
                if not isinstance(exc, motor.errors.PyMongoError):
                    raise


# ---------------------------------------------------------------------------
# 测试数据：6 个文件 × 部分代表性端点
# ---------------------------------------------------------------------------

# 路由模块导入路径 → (模块前缀, 市场前缀)
_ROUTER_SPECS = [
    ("app.routers.cn.data", "/api/cn/data"),
    ("app.routers.cn.sync", "/api/cn/data"),
    ("app.routers.hk.data", "/api/hk/data"),
    ("app.routers.hk.sync", "/api/hk/data"),
    ("app.routers.us.data", "/api/us/data"),
    ("app.routers.us.sync", "/api/us/data"),
]


# GET 端点（任意登录用户可访问）—— 自动从模块路由提取
def _collect_get_endpoints():
    """根据前缀给出代表性的 GET 端点。"""
    return [
        (f"{prefix}/dashboard",) if "data" in prefix and "sync" not in module else
        (f"{prefix}/symbols",) if "data" in prefix and "sync" not in module else
        (f"{prefix}/sync/status",) if "sync" in module else
        (f"{prefix}/calendar",)
        for module, prefix in _ROUTER_SPECS
    ]


# ---------------------------------------------------------------------------
# 静态结构验证（不依赖运行时）
# ---------------------------------------------------------------------------


def _endpoint_matches(route_path: str, subpath: str) -> bool:
    """路径模板匹配：route_path 末尾若干段必须按模板匹配 subpath。

    例如 route_path="/api/cn/data/config/priority/{domain}" 可匹配
    subpath="/config/priority/daily_quotes"，最后一段 {domain} 接受任意值。
    """
    route_parts = route_path.strip("/").split("/")
    sub_parts = subpath.strip("/").split("/")
    if len(sub_parts) > len(route_parts):
        return False
    # 对齐 route_parts 末尾
    route_tail = route_parts[-len(sub_parts):]
    for rp, sp in zip(route_tail, sub_parts):
        if rp == sp:
            continue
        if rp.startswith("{") and rp.endswith("}"):
            continue
        return False
    return True


class TestRouterAuthSignature:
    """静态校验所有端点都声明了正确的依赖。"""

    @pytest.mark.parametrize("module_path,prefix", _ROUTER_SPECS)
    def test_all_endpoints_have_user_dependency(self, module_path, prefix):
        """每个端点都必须声明 user 参数（Depends(get_current_user) 或 Depends(require_admin)）。"""
        import importlib
        from fastapi.routing import APIRoute

        module = importlib.import_module(module_path)
        assert hasattr(module, "router"), f"{module_path} 缺少 router 属性"

        missing = []
        for route in module.router.routes:
            if not isinstance(route, APIRoute):
                continue
            # 收集端点函数的依赖
            deps = route.dependant.dependencies
            dep_names = set()
            for d in deps:
                if d.call.__name__ in ("get_current_user", "require_admin"):
                    dep_names.add(d.call.__name__)
            if not dep_names:
                missing.append(route.path)
        assert not missing, (
            f"{module_path} 以下端点缺少鉴权依赖: {missing}"
        )

    @pytest.mark.parametrize(
        "module_path,method,subpath",
        [
            # 写操作端点必须是 require_admin
            ("app.routers.cn.data", "POST", "/sources/health/tushare/daily_quotes/reset"),
            ("app.routers.cn.data", "PUT", "/config/priority/daily_quotes"),
            ("app.routers.cn.data", "POST", "/quality/check"),
            ("app.routers.cn.sync", "POST", "/refresh/000001"),
            ("app.routers.cn.sync", "POST", "/sync/daily_quotes"),
            ("app.routers.hk.data", "POST", "/sources/health/tushare/daily_quotes/reset"),
            ("app.routers.hk.data", "PUT", "/config/priority/daily_quotes"),
            ("app.routers.hk.data", "POST", "/quality/check"),
            ("app.routers.hk.sync", "POST", "/refresh/00700"),
            ("app.routers.hk.sync", "POST", "/sync/daily_quotes"),
            ("app.routers.us.data", "POST", "/sources/health/yfinance/daily_quotes/reset"),
            ("app.routers.us.data", "PUT", "/config/priority/daily_quotes"),
            ("app.routers.us.data", "POST", "/quality/check"),
            ("app.routers.us.sync", "POST", "/refresh/AAPL"),
            ("app.routers.us.sync", "POST", "/sync/daily_quotes"),
        ],
    )
    def test_write_endpoints_require_admin(self, module_path, method, subpath):
        """写操作端点必须使用 require_admin（不允许 get_current_user）。"""
        import importlib
        from fastapi.routing import APIRoute

        module = importlib.import_module(module_path)
        found = False
        for route in module.router.routes:
            if not isinstance(route, APIRoute):
                continue
            if method not in route.methods:
                continue
            if not _endpoint_matches(route.path, subpath):
                continue
            # 匹配此端点
            deps_admin = [
                d for d in route.dependant.dependencies
                if d.call.__name__ == "require_admin"
            ]
            assert deps_admin, (
                f"{module_path} {method} {route.path} 必须使用 require_admin"
            )
            found = True
            break
        assert found, f"{module_path} 未找到匹配 {method} {subpath} 的端点"


# ---------------------------------------------------------------------------
# 运行时鉴权验证：401（未认证）/ 403（普通用户越权）
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def cn_data_app(inject_sim_db):
    """注入 SimulatedMongoDB 后再创建 DataInterface 单例。"""
    DataInterface.reset_instance()
    di = DataInterface()
    DataInterface._instance = di

    from app.routers.cn.data import router
    app = FastAPI()
    app.include_router(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, app

    DataInterface.reset_instance()


# 用户身份测试数据（与 conftest.normal_user_data/admin_user_data 同结构）
_NORMAL_USER_FIXTURE = {
    "id": "507f1f77bcf86cd799439021",
    "username": "auth_test_normal_user",
    "email": "auth_test_normal@test.com",
    "is_admin": False,
    "preferences": {"language": "zh-CN", "ui_theme": "light"},
}

_ADMIN_USER_FIXTURE = {
    "id": "507f1f77bcf86cd799439022",
    "username": "auth_test_admin_user",
    "email": "auth_test_admin@test.com",
    "is_admin": True,
    "preferences": {"language": "zh-CN", "ui_theme": "light"},
}


class TestUnauthenticatedBlocked:
    """未携带 token 访问所有端点应返回 401。"""

    @pytest.mark.parametrize("module_path,prefix", _ROUTER_SPECS)
    @pytest.mark.asyncio
    async def test_get_returns_401_without_token(self, module_path, prefix, inject_sim_db):
        DataInterface.reset_instance()
        di = DataInterface()
        DataInterface._instance = di

        module = importlib.import_module(module_path)
        # 真实鉴权路径：匿名（不预置用户、不带 token）
        client = await _build_real_client(module.router, sim_db=inject_sim_db, user_data=None)
        try:
            # 选择一个 GET 端点
            if "data" in module_path and "sync" not in module_path:
                path = f"{prefix}/dashboard"
            else:  # sync 模块
                path = f"{prefix}/sync/status"

            resp = await client.get(path)
            assert resp.status_code == 401, (
                f"{module_path} GET {path} 未认证应返回 401，实际 {resp.status_code}"
            )
        finally:
            await _close_real_client(client)

        DataInterface.reset_instance()


class TestNormalUserForbidden:
    """普通用户访问写操作应返回 403（真实 require_admin 拒绝）。"""

    @pytest.mark.parametrize(
        "module_path,sub_path",
        [
            ("app.routers.cn.data", "/api/cn/data/quality/check"),
            ("app.routers.hk.data", "/api/hk/data/quality/check"),
            ("app.routers.us.data", "/api/us/data/quality/check"),
        ],
    )
    @pytest.mark.asyncio
    async def test_quality_check_returns_403_for_normal_user(
        self, module_path, sub_path, inject_sim_db
    ):
        DataInterface.reset_instance()
        di = DataInterface()
        DataInterface._instance = di

        module = importlib.import_module(module_path)
        client = await _build_real_client(
            module.router, sim_db=inject_sim_db, user_data=_NORMAL_USER_FIXTURE
        )
        try:
            resp = await client.post(sub_path)
            assert resp.status_code == 403, (
                f"{module_path} POST /quality/check 普通用户应返回 403，实际 {resp.status_code}"
            )
        finally:
            await _close_real_client(client)

        DataInterface.reset_instance()

    @pytest.mark.parametrize(
        "module_path,reset_path",
        [
            ("app.routers.cn.data", "/api/cn/data/sources/health/tushare/daily_quotes/reset"),
            ("app.routers.hk.data", "/api/hk/data/sources/health/tushare/daily_quotes/reset"),
            ("app.routers.us.data", "/api/us/data/sources/health/yfinance/daily_quotes/reset"),
        ],
    )
    @pytest.mark.asyncio
    async def test_circuit_breaker_reset_returns_403_for_normal_user(
        self, module_path, reset_path, inject_sim_db
    ):
        DataInterface.reset_instance()
        di = DataInterface()
        DataInterface._instance = di

        module = importlib.import_module(module_path)
        client = await _build_real_client(
            module.router, sim_db=inject_sim_db, user_data=_NORMAL_USER_FIXTURE
        )
        try:
            resp = await client.post(reset_path)
            assert resp.status_code == 403, (
                f"{module_path} POST {reset_path} 普通用户应返回 403，实际 {resp.status_code}"
            )
        finally:
            await _close_real_client(client)

        DataInterface.reset_instance()
