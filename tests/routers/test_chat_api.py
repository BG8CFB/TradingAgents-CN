"""/api/chat 路由测试 — HTTP 端到端（会话 CRUD / 202 run_id）+ 直调错误分支（404/503/429/409）。

注意：202 用例会真实创建后台 run（无 mock）；模型未配置时 run 走 failed 落库，
模型已配置的环境会触发一次真实 LLM 调用（消耗少量 token）。
WS 端点无测试（项目内无 WS 端到端测试先例，见交付说明）。
"""
import asyncio

import pytest

pytestmark = pytest.mark.requires_db

from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.data.storage.mongo.repositories.chat_repo import (
    AUDIT_COLLECTION,
    MESSAGES_COLLECTION,
    SESSIONS_COLLECTION,
    ChatRepo,
)
from app.routers.chat import (
    SendMessageRequest,
    get_quota,
    get_session,
    send_message,
)
from app.utils.passwords import hash_password
from app.utils.timezone import now_tz
from app.utils.time_utils import now_utc

USER = "chat_api_user"
USER_ID = "507f1f77bcf86cd799430001"
OTHER_ID = "507f1f77bcf86cd799430002"


@pytest.fixture
async def chat_api_env(real_mongo_db):
    """真实 MongoDB + 真实 JWT 用户 + chat 三集合/配置集合清空 + config 子服务缓存复位。"""
    from app.services.auth_service import AuthService
    from app.services.config import config_service
    from app.services.user_service import user_service

    db = real_mongo_db
    for coll in (SESSIONS_COLLECTION, MESSAGES_COLLECTION, AUDIT_COLLECTION):
        await db[coll].delete_many({})
    await db.system_configs.delete_many({"config_name": "chat-api-test"})

    original_user_db = user_service.db
    user_service.set_database(db)
    await db.users.delete_many({"username": USER})
    await db.users.insert_one({
        "_id": USER_ID,
        "username": USER,
        "email": "chat_api@test.com",
        "hashed_password": hash_password("Test@1234"),
        "is_admin": False, "is_active": True,
        "created_at": now_utc(), "preferences": {},
    })
    token = AuthService.create_access_token(sub=USER)

    original_config_db = config_service._system.db
    config_service._system.db = None

    app = FastAPI()
    from app.routers.chat import router
    app.include_router(router)

    yield {"db": db, "token": token, "user": {"id": USER_ID}, "app": app}

    config_service._system.db = None
    config_service._system.db = original_config_db
    user_service.set_database(original_user_db)
    await db.users.delete_many({"username": USER})
    for coll in (SESSIONS_COLLECTION, MESSAGES_COLLECTION, AUDIT_COLLECTION):
        await db[coll].delete_many({})
    await db.system_configs.delete_many({"config_name": "chat-api-test"})


async def _seed_enabled_settings(db, *, enabled=True, limit=20):
    """插入 chat 测试配置；version 取当前最高+1（get_system_config 按 version 倒序取活跃配置，
    真库可能已有更高版本的用户配置，version=1 会被覆盖）。"""
    highest = await db.system_configs.find_one({"is_active": True}, sort=[("version", -1)])
    await db.system_configs.insert_one({
        "config_name": "chat-api-test", "config_type": "system",
        "system_settings": {"chat_enabled": enabled, "chat_daily_limit": limit},
        "version": (highest.get("version", 0) + 1) if highest else 1,
        "is_active": True,
    })


# ── HTTP 端到端 ──────────────────────────────────────────────


async def test_http_session_crud_flow(chat_api_env):
    """POST/GET/DELETE /sessions：success 信封 + 软删后 404（真实 JWT 鉴权路径）。"""
    env = chat_api_env
    headers = {"Authorization": f"Bearer {env['token']}"}
    async with AsyncClient(transport=ASGITransport(app=env["app"]),
                           base_url="http://testserver") as ac:
        created = await ac.post("/api/chat/sessions", headers=headers)
        assert created.status_code == 200
        body = created.json()
        assert body["success"] is True
        session_id = body["data"]["session_id"]
        assert session_id.startswith("sess_")

        listed = await ac.get("/api/chat/sessions", headers=headers)
        assert listed.status_code == 200
        payload = listed.json()["data"]
        assert payload["total"] >= 1
        assert any(s["session_id"] == session_id for s in payload["sessions"])

        detail = await ac.get(f"/api/chat/sessions/{session_id}", headers=headers)
        assert detail.status_code == 200
        d = detail.json()["data"]
        assert d["session"]["session_id"] == session_id
        assert d["messages"] == []

        deleted = await ac.delete(f"/api/chat/sessions/{session_id}", headers=headers)
        assert deleted.status_code == 200
        assert deleted.json()["data"]["status"] == "archived"

        gone = await ac.get(f"/api/chat/sessions/{session_id}", headers=headers)
        assert gone.status_code == 404


async def test_http_send_message_202_returns_run_id(chat_api_env):
    """启用 + 配额充足 → 202 {success, data:{run_id, quota_remaining}}（回答走 WS）。"""
    env = chat_api_env
    await _seed_enabled_settings(env["db"])
    svc_session = await ChatRepo().create_session(USER_ID)
    headers = {"Authorization": f"Bearer {env['token']}"}
    async with AsyncClient(transport=ASGITransport(app=env["app"]),
                           base_url="http://testserver") as ac:
        resp = await ac.post(
            f"/api/chat/sessions/{svc_session['session_id']}/messages",
            json={"content": "测试提问"},
            headers=headers,
        )
    assert resp.status_code == 202
    body = resp.json()
    assert body["success"] is True
    run_id = body["data"]["run_id"]
    assert run_id.startswith("run_")
    assert isinstance(body["data"]["quota_remaining"], int)
    # 给后台 run 一个调度机会（无论成败都会落审计并释放会话锁）
    await asyncio.sleep(0.3)


async def test_http_quota_endpoint(chat_api_env):
    """GET /api/chat/quota：默认 limit 20、无用量 → 剩 20。"""
    resp = await get_quota(user={"id": USER_ID})
    assert resp["success"] is True
    assert resp["data"]["quota_remaining"] == 20


# ── 直调错误分支（start_run 之前，无后台任务） ────────────────


async def test_send_message_404_unknown_session(chat_api_env):
    with pytest.raises(HTTPException) as exc:
        await send_message("sess_not_exist", SendMessageRequest(content="hi"),
                           user={"id": USER_ID})
    assert exc.value.status_code == 404


async def test_send_message_503_disabled(chat_api_env):
    """无 chat_enabled 设置（默认关）→ 503。"""
    session = await ChatRepo().create_session(USER_ID)
    with pytest.raises(HTTPException) as exc:
        await send_message(session["session_id"], SendMessageRequest(content="hi"),
                           user={"id": USER_ID})
    assert exc.value.status_code == 503


async def test_send_message_429_quota_exhausted(chat_api_env):
    """limit=1 且当日已有 1 条 done → 429。"""
    env = chat_api_env
    await _seed_enabled_settings(env["db"], limit=1)
    session = await ChatRepo().create_session(USER_ID)
    await ChatRepo().insert_audit({
        "user_id": USER_ID, "session_id": session["session_id"], "status": "done",
        "created_at": now_tz().isoformat(),
    })
    with pytest.raises(HTTPException) as exc:
        await send_message(session["session_id"], SendMessageRequest(content="hi"),
                           user={"id": USER_ID})
    assert exc.value.status_code == 429


async def test_send_message_409_session_busy(chat_api_env):
    """会话锁被占用（同会话上一轮进行中）→ 409。"""
    from app.services.chat.conversation_runner import get_session_lock

    env = chat_api_env
    await _seed_enabled_settings(env["db"])
    session = await ChatRepo().create_session(USER_ID)
    lock = get_session_lock(session["session_id"])
    await lock.acquire()
    try:
        with pytest.raises(HTTPException) as exc:
            await send_message(session["session_id"], SendMessageRequest(content="hi"),
                               user={"id": USER_ID})
        assert exc.value.status_code == 409
    finally:
        lock.release()


async def test_get_session_404_for_foreign_user(chat_api_env):
    """他人会话 → 404（不泄露存在性）。"""
    session = await ChatRepo().create_session(USER_ID)
    with pytest.raises(HTTPException) as exc:
        await get_session(session["session_id"], user={"id": OTHER_ID})
    assert exc.value.status_code == 404


async def test_send_message_rejects_blank_content():
    """空白内容被 pydantic 拒绝（1-4000 字符约束）。"""
    with pytest.raises(ValidationError):
        SendMessageRequest(content="")
