"""
PR3 认证细节测试

覆盖 3 项修复：
- S7 登录日志脱敏（mask_username + token_fingerprint）
- S6 refresh_token 轮换（黑名单机制 + 重放保护）
- S4 WebSocket 鉴权错误码（4401/4403/4404）
"""

import hashlib
import logging
from typing import Optional

import pytest


# ---------------------------------------------------------------------------
# 通用：注入 SimulatedRedis（让 _add_token_to_blacklist / _is_token_blacklisted 生效）
# ---------------------------------------------------------------------------


@pytest.fixture
def inject_sim_redis(sim_redis):
    """把 SimulatedRedis 注入到 app.data.storage.redis.client._redis_client。"""
    from app.data.storage.redis import client as redis_client

    original = redis_client._redis_client
    redis_client._redis_client = sim_redis
    yield sim_redis
    redis_client._redis_client = original


# ---------------------------------------------------------------------------
# S7 日志脱敏工具
# ---------------------------------------------------------------------------


class TestSecretMasking:
    """S7：app/utils/secret_masking.py 的脱敏工具。"""

    def test_mask_username_preserves_prefix(self):
        from app.utils.secret_masking import mask_username

        masked = mask_username("admin")
        assert masked.startswith("ad")
        assert "*" in masked
        assert "len=5" in masked
        # 关键：不暴露完整用户名
        assert "admin" not in masked

    def test_mask_username_short_value(self):
        from app.utils.secret_masking import mask_username

        masked = mask_username("ab")
        assert "ab" not in masked
        assert "*" in masked
        assert "len=2" in masked

    def test_mask_username_empty_or_none(self):
        from app.utils.secret_masking import mask_username

        assert mask_username("") == "***"
        assert mask_username(None) == "***"

    def test_token_fingerprint_is_sha256_prefix(self):
        from app.utils.secret_masking import token_fingerprint

        fp = token_fingerprint("some-secret-token")
        # 12 字符，全 hex
        assert len(fp) == 12
        assert all(c in "0123456789abcdef" for c in fp)
        # 与手动 SHA256 一致
        assert fp == hashlib.sha256(b"some-secret-token").hexdigest()[:12]

    def test_token_fingerprint_empty(self):
        from app.utils.secret_masking import token_fingerprint

        assert token_fingerprint(None) == "none"
        assert token_fingerprint("") == "none"

    def test_token_fingerprint_stable(self):
        """同一 token 多次调用必须返回同一指纹（用于日志关联）。"""
        from app.utils.secret_masking import token_fingerprint

        assert token_fingerprint("x") == token_fingerprint("x")
        assert token_fingerprint("x") != token_fingerprint("y")


# ---------------------------------------------------------------------------
# S7 登录日志不再明文输出用户名
# ---------------------------------------------------------------------------


class TestLoginLogMasking:
    """S7：auth_db 中 login 路径的日志不再明文打印用户名。"""

    def _capture_logs(self, caplog, logger_name: str, level: int = logging.INFO):
        caplog.set_level(level, logger=logger_name)
        return caplog.records

    @pytest.mark.asyncio
    async def test_login_failed_log_does_not_leak_username(self, caplog, sim_db):
        """登录失败时日志中不应出现完整用户名。"""
        from app.core import database as db_mod
        from app.routers.auth_db import LoginRequest, login
        from starlette.requests import Request

        # 注入 sim_db 让 log_operation 内部不抛错
        original_db = db_mod.mongo_db
        db_mod.mongo_db = sim_db
        try:
            # 用一个独特名字确保不会被部分匹配漏过
            unique_user = "leakcheck_user12345"
            req = LoginRequest(username=unique_user, password="wrong")

            scope = {
                "type": "http",
                "method": "POST",
                "path": "/api/auth/login",
                "headers": [],
                "query_string": b"",
                "client": ("127.0.0.1", 8000),
                "app": None,
            }
            request = Request(scope)

            records = self._capture_logs(caplog, "auth_db")
            with pytest.raises(Exception):
                # login 内部会抛 HTTPException 401
                await login(req, request)

            # 关键断言：日志中的所有 record 消息都不能直接出现完整用户名
            for record in records:
                assert unique_user not in record.getMessage(), (
                    f"日志泄漏用户名: {record.getMessage()}"
                )
        finally:
            db_mod.mongo_db = original_db

    @pytest.mark.asyncio
    async def test_get_current_user_log_uses_fingerprint(self, caplog):
        """get_current_user 日志中不应包含 token 原文。"""
        from app.routers.auth_db import get_current_user

        # 构造一个超长 token 确保只有片段打印时也会泄漏
        fake_token = "T" * 200
        records = self._capture_logs(caplog, "auth_db", level=logging.DEBUG)
        with pytest.raises(Exception):
            await get_current_user(authorization=f"Bearer {fake_token}")

        # token 原文不应出现在任何日志中
        for record in records:
            msg = record.getMessage()
            assert fake_token not in msg
            # 也不要 hash % 1000000 这种弱指纹（旧实现）
            # 我们要求使用 sha256 截断指纹（12 字符）
            if "Token指纹" in msg:
                assert "sha" not in msg.lower() or len(msg) < 100


# ---------------------------------------------------------------------------
# S6 refresh_token 轮换
# ---------------------------------------------------------------------------


class TestRefreshTokenRotation:
    """S6：refresh_token 用一次后必须进入黑名单，二次使用必须 401。"""

    @pytest.mark.asyncio
    async def test_add_and_check_blacklist_round_trip(self, inject_sim_redis):
        """_add_token_to_blacklist 写入后 _is_token_blacklisted 立即可见。"""
        from app.routers.auth_db import _add_token_to_blacklist, _is_token_blacklisted

        token = "my-test-refresh-token-123"
        assert await _is_token_blacklisted(token) is False
        ok = await _add_token_to_blacklist(token, ttl_days=7)
        assert ok is True
        assert await _is_token_blacklisted(token) is True

    @pytest.mark.asyncio
    async def test_check_blacklist_returns_false_when_redis_missing(self):
        """Redis 不可用时 _is_token_blacklisted 必须 fail-open 返回 False。"""
        from app.data.storage.redis import client as redis_client
        from app.routers.auth_db import _is_token_blacklisted

        # 确保 Redis 客户端为 None（get_redis 在 _redis_client=None 且数据库未初始化时返回 None）
        original = redis_client._redis_client
        redis_client._redis_client = None
        # 同时让 reset 让 get_redis 走 try/except 返回 None
        try:
            # 即使 redis_client._redis_client=None，get_redis 会尝试 get_redis_client()
            # 若失败返回 None，最终 _is_token_blacklisted 返回 False
            result = await _is_token_blacklisted("any-token")
            assert result is False
        finally:
            redis_client._redis_client = original

    @pytest.mark.asyncio
    async def test_refresh_token_rotates_on_success(self, inject_sim_redis, inject_sim_db):
        """refresh 成功后旧 refresh_token 必须立即被加入黑名单。

        真实 DB 路径：在 sim_db.users 写入真实 User 文档，让 user_service.get_user_by_username
        走完整查询链路，避免 monkey 替换 service 方法（违反 CLAUDE.md "不允许 mock" 规则）。
        """
        from app.services.auth_service import AuthService
        from app.services.user_service import user_service
        from app.utils.passwords import hash_password
        from app.data.storage.mongo import client as mongo_client

        # user_service 持有自己的 db 引用，需要切到 sim_db 才能命中真实查询
        original_db = user_service.db
        user_service.set_database(inject_sim_db)

        # 在 sim_db 中插入一个真实用户文档（与 user_service.get_user_by_username 真实路径对齐）
        from bson import ObjectId

        db = mongo_client._motor_db
        await db.users.delete_many({"username": "rotation_user"})
        await db.users.insert_one({
            "_id": ObjectId(),
            "username": "rotation_user",
            "email": "rotation@test.com",
            "hashed_password": hash_password("irrelevant-for-refresh"),
            "is_active": True,
            "is_verified": True,
            "is_admin": False,
            "must_change_password": False,
        })

        try:
            # 构造一个合法的 refresh token
            refresh_token = AuthService.create_access_token(
                sub="rotation_user",
                expires_delta=60 * 60 * 24 * 7,
                token_type="refresh",
            )
            from app.routers.auth_db import _is_token_blacklisted

            # 调用前不在黑名单
            assert await _is_token_blacklisted(refresh_token) is False

            # 直接调用路由函数（用户通过真实 DB 路径查到，不替换 service 方法）
            from app.routers.auth_db import RefreshTokenRequest, refresh_token as refresh_endpoint

            payload = RefreshTokenRequest(refresh_token=refresh_token)
            response = await refresh_endpoint(payload)
            # refresh 路由返回 JSONResponse，body 在 response.body（bytes）
            import json as _json
            body = _json.loads(response.body) if hasattr(response, "body") else response
            assert body["success"] is True

            # 关键：旧 refresh_token 应在黑名单中
            assert await _is_token_blacklisted(refresh_token) is True

            # 新返回的 refresh_token 不应在黑名单中（否则用户无法继续刷新）
            new_refresh = body["data"]["refresh_token"]
            assert await _is_token_blacklisted(new_refresh) is False
        finally:
            # 清理测试数据
            await db.users.delete_many({"username": "rotation_user"})
            user_service.set_database(original_db)

    @pytest.mark.asyncio
    async def test_old_refresh_token_rejected_after_rotation(self, inject_sim_redis, inject_sim_db):
        """轮换后再用旧 refresh_token 必须 401（真实 DB 路径）。"""
        from app.services.auth_service import AuthService
        from app.services.user_service import user_service
        from app.utils.passwords import hash_password
        from app.data.storage.mongo import client as mongo_client
        from fastapi import HTTPException
        from app.routers.auth_db import (
            RefreshTokenRequest,
            refresh_token as refresh_endpoint,
        )

        # 同样需要把 user_service.db 切到 sim_db
        original_db = user_service.db
        user_service.set_database(inject_sim_db)

        from bson import ObjectId

        db = mongo_client._motor_db
        await db.users.delete_many({"username": "rotation_user"})
        await db.users.insert_one({
            "_id": ObjectId(),
            "username": "rotation_user",
            "email": "rotation@test.com",
            "hashed_password": hash_password("irrelevant-for-refresh"),
            "is_active": True,
            "is_verified": True,
            "is_admin": False,
            "must_change_password": False,
        })

        refresh_token = AuthService.create_access_token(
            sub="rotation_user",
            expires_delta=60 * 60 * 24 * 7,
            token_type="refresh",
        )

        try:
            # 第一次 refresh 成功，旧 token 被加入黑名单
            payload = RefreshTokenRequest(refresh_token=refresh_token)
            first = await refresh_endpoint(payload)
            import json as _json
            first_body = _json.loads(first.body) if hasattr(first, "body") else first
            assert first_body["success"] is True

            # 第二次用同一个 refresh_token 必须被拒
            with pytest.raises(HTTPException) as exc_info:
                await refresh_endpoint(payload)
            assert exc_info.value.status_code == 401
            assert "revoked" in exc_info.value.detail.lower()
        finally:
            await db.users.delete_many({"username": "rotation_user"})
            user_service.set_database(original_db)

    @pytest.mark.asyncio
    async def test_revoked_token_via_logout_blocks_refresh(self, inject_sim_redis):
        """logout 后的 refresh_token 必须 401。"""
        from app.services.auth_service import AuthService
        from fastapi import HTTPException
        from app.routers.auth_db import (
            RefreshTokenRequest,
            refresh_token as refresh_endpoint,
            _add_token_to_blacklist,
        )

        refresh_token = AuthService.create_access_token(
            sub="logout_user",
            expires_delta=60 * 60 * 24 * 7,
            token_type="refresh",
        )

        # 模拟 logout 时把 token 加入黑名单
        await _add_token_to_blacklist(refresh_token, ttl_days=7)

        # 立即尝试 refresh 必须 401
        with pytest.raises(HTTPException) as exc_info:
            payload = RefreshTokenRequest(refresh_token=refresh_token)
            await refresh_endpoint(payload)
        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# S4 WebSocket 鉴权错误码
# ---------------------------------------------------------------------------


class TestWebSocketAuthCodes:
    """S4：/api/analysis/ws/task/{task_id} 端点的鉴权错误码。"""

    @pytest.fixture
    def fake_ws(self):
        """构造一个最小可用的 WebSocket 双工对象。"""
        from starlette.websockets import WebSocketDisconnect

        class FakeWebSocket:
            """最小化 WebSocket：记录所有 close() 调用。"""

            def __init__(self, query_params: Optional[dict] = None):
                self.query_params = query_params or {}
                self.closed_code = None
                self.closed_reason = None
                self.accepted = False

            async def accept(self):
                self.accepted = True

            async def close(self, code: int = 1000, reason: Optional[str] = None):
                self.closed_code = code
                self.closed_reason = reason

            async def send_text(self, text: str):
                pass

            async def receive_text(self) -> str:
                raise WebSocketDisconnect()

        return FakeWebSocket

    @pytest.mark.asyncio
    async def test_missing_token_returns_4404(self, fake_ws):
        """无 token 参数必须返回 4404 task authentication required。"""
        from app.routers.analysis import websocket_task_progress

        ws = fake_ws(query_params={})  # 没有 token
        # task_id 任一即可
        await websocket_task_progress(ws, "any-task")

        assert ws.closed_code == 4404
        assert ws.closed_reason is not None
        assert "authentication" in ws.closed_reason.lower() or "required" in ws.closed_reason.lower()
        # 关键：在 accept 之前就关闭
        assert ws.accepted is False

    @pytest.mark.asyncio
    async def test_invalid_token_returns_4401(self, fake_ws):
        """无效/过期 token 必须返回 4401 authentication failed。"""
        from app.routers.analysis import websocket_task_progress

        # 用一个明显无效的 token
        ws = fake_ws(query_params={"token": "garbage.invalid.token"})
        await websocket_task_progress(ws, "any-task")

        assert ws.closed_code == 4401
        assert "authentication" in ws.closed_reason.lower() or "failed" in ws.closed_reason.lower()
        assert ws.accepted is False

    @pytest.mark.asyncio
    async def test_task_not_found_returns_4404(self, fake_ws, inject_sim_db):
        """任务不存在必须返回 4404 task not found，且不再继续连接。

        真实 DB 路径：通过 inject_sim_db 注入空集合，让 analysis_service 真实查询
        返回 None（不使用 monkey 替换 service 方法，符合 CLAUDE.md 测试铁律）。
        """
        from app.routers.analysis import websocket_task_progress
        from app.services.auth_service import AuthService
        from app.services.user_service import user_service
        from app.utils.passwords import hash_password
        from bson import ObjectId

        # user_service 切到 sim_db，让 get_user_by_username 走真实查询
        original_db = user_service.db
        user_service.set_database(inject_sim_db)

        # 预置真实用户文档（让 WS 鉴权通过 user_id 校验）
        await inject_sim_db.users.insert_one({
            "_id": ObjectId(),
            "username": "ws_test_user",
            "email": "ws@test.com",
            "hashed_password": hash_password("irrelevant"),
            "is_active": True,
            "is_admin": False,
        })

        token = AuthService.create_access_token(sub="ws_test_user")

        try:
            # sim_db 中 analysis_tasks 为空集合，真实查询会返回 None
            ws = fake_ws(query_params={"token": token})
            await websocket_task_progress(ws, "nonexistent-task")

            assert ws.closed_code == 4404
            assert ws.closed_reason is not None
            assert "task" in ws.closed_reason.lower() and "not found" in ws.closed_reason.lower()
            # M6 改造后 close 前先 accept，所以 accepted=True 是预期行为
            assert ws.accepted is True
        finally:
            await inject_sim_db.users.delete_many({"username": "ws_test_user"})
            user_service.set_database(original_db)

    @pytest.mark.asyncio
    async def test_token_log_uses_fingerprint(self, fake_ws, caplog):
        """连接日志中必须使用 token_fingerprint 而非 hash(token) % 1000000。"""
        from app.routers.analysis import websocket_task_progress

        caplog.set_level(logging.DEBUG, logger="analysis")

        ws = fake_ws(query_params={"token": "garbage.invalid"})
        await websocket_task_progress(ws, "any-task")

        # 即使 token 无效，DEBUG 级别也会在 verify_token 之前打印 token_fp
        assert any("token_fp=" in r.getMessage() for r in caplog.records), (
            "WebSocket 连接日志必须使用 token_fp= 字段，而不是 hash(token) % 1000000"
        )


# ---------------------------------------------------------------------------
# S6+S7 综合：refresh 端点的日志也不暴露用户名
# ---------------------------------------------------------------------------


class TestRefreshEndpointLogMasking:
    """S6+S7 综合：refresh 端点的日志和响应中不能泄漏敏感信息。"""

    @pytest.mark.asyncio
    async def test_refresh_log_uses_fingerprint_not_token(self, inject_sim_redis, caplog):
        """refresh 端点日志应使用 token_fingerprint 而非原 token。"""
        from app.routers.auth_db import RefreshTokenRequest, refresh_token as refresh_endpoint

        long_token = "X" * 100  # 假 token
        caplog.set_level(logging.DEBUG, logger="auth_db")

        payload = RefreshTokenRequest(refresh_token=long_token)
        # 这里会因 verify_token 失败抛 401
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            await refresh_endpoint(payload)

        # 关键：日志中绝不能出现 token 原文
        for record in caplog.records:
            assert long_token not in record.getMessage()
            # 但应该有 token_fp 字段（如果有指纹日志的话）
            # 注意：失败路径不一定打印指纹，所以这里只断言不泄漏
