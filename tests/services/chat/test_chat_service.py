"""ChatService 单元层测试 — 设置读取 / 配额 / 会话 CRUD / 首条定题（真实 MongoDB）。

用 real_mongo_db 而非 SimulatedMongoDB：touch_session 依赖 $set+$inc 组合更新、
count_today_done 依赖 $regex、list_messages 依赖真实排序，模拟库均不支持。
"""
import pytest

pytestmark = pytest.mark.requires_db

from app.data.storage.mongo.repositories.chat_repo import (
    AUDIT_COLLECTION,
    MESSAGES_COLLECTION,
    SESSIONS_COLLECTION,
    ChatRepo,
)
from app.services.chat import ChatService, QuotaExceededError
from app.services.chat.chat_service import DEFAULT_CHAT_SYSTEM_PROMPT
from app.utils.timezone import now_tz

USER = "chat_svc_user"


@pytest.fixture
async def chat_env(real_mongo_db):
    """清 chat 三集合 + 重置 config 子服务 db 缓存（防跨用例串库）。"""
    from app.services.config import config_service

    db = real_mongo_db
    await db[SESSIONS_COLLECTION].delete_many({})
    await db[MESSAGES_COLLECTION].delete_many({})
    await db[AUDIT_COLLECTION].delete_many({})
    await db.system_configs.delete_many({"config_name": "chat-test"})
    original_db = config_service._system.db
    config_service._system.db = None
    yield db
    config_service._system.db = None
    config_service._system.db = original_db
    for coll in (SESSIONS_COLLECTION, MESSAGES_COLLECTION, AUDIT_COLLECTION):
        await db[coll].delete_many({})


async def _seed_settings(db, settings: dict):
    """插入 chat 测试配置（version 取最高+1，避免被真库既有活跃配置覆盖）。"""
    highest = await db.system_configs.find_one({"is_active": True}, sort=[("version", -1)])
    await db.system_configs.insert_one({
        "config_name": "chat-test", "config_type": "system",
        "system_settings": settings,
        "version": (highest.get("version", 0) + 1) if highest else 1,
        "is_active": True,
    })


async def test_settings_defaults(chat_env):
    """无 system_configs → 全默认：enabled=False / limit=20 / 内置提示词 / mcp 关。"""
    svc = ChatService()
    s = await svc.get_settings()
    assert s["enabled"] is False
    assert s["daily_limit"] == 20
    assert s["model"] == ""
    assert s["prompt"] == DEFAULT_CHAT_SYSTEM_PROMPT
    assert s["enable_mcp"] is False


async def test_settings_from_db(chat_env):
    """system_settings 透传：enabled=True / limit=3 / 自定义模型与提示词。"""
    await _seed_settings(chat_env, {
        "chat_enabled": True, "chat_daily_limit": 3,
        "chat_model": "test-model", "chat_system_prompt": "自定义",
        "chat_enable_mcp": True,
    })
    s = await ChatService().get_settings()
    assert s["enabled"] is True
    assert s["daily_limit"] == 3
    assert s["model"] == "test-model"
    assert s["prompt"] == "自定义"
    assert s["enable_mcp"] is True


async def test_quota_counts_today_done_only(chat_env):
    """配额只数当日 status=done；failed 不计。"""
    today = now_tz().strftime("%Y-%m-%d")
    await _seed_settings(chat_env, {"chat_enabled": True, "chat_daily_limit": 2})
    repo = ChatRepo()
    await repo.insert_audit({"user_id": USER, "session_id": "s1", "status": "done",
                             "created_at": f"{today}T10:00:00"})
    await repo.insert_audit({"user_id": USER, "session_id": "s1", "status": "failed",
                             "created_at": f"{today}T11:00:00"})
    # 他人的用量不串
    await repo.insert_audit({"user_id": "other", "session_id": "s2", "status": "done",
                             "created_at": f"{today}T12:00:00"})
    svc = ChatService()
    assert await svc.quota_remaining(USER) == 1
    remaining = await svc.check_quota(USER)
    assert remaining == 1


async def test_check_quota_raises_when_exhausted(chat_env):
    """配额用尽 → QuotaExceededError。"""
    today = now_tz().strftime("%Y-%m-%d")
    await _seed_settings(chat_env, {"chat_enabled": True, "chat_daily_limit": 1})
    await ChatRepo().insert_audit({"user_id": USER, "session_id": "s1", "status": "done",
                                   "created_at": f"{today}T10:00:00"})
    svc = ChatService()
    assert await svc.quota_remaining(USER) == 0
    with pytest.raises(QuotaExceededError):
        await svc.check_quota(USER)


async def test_session_crud_flow(chat_env):
    """create → list → get → archive（软删）→ 不再出现在列表与详情。"""
    svc = ChatService()
    created = await svc.create_session(USER)
    assert created["session_id"].startswith("sess_")
    assert created["status"] == "active"

    items, total = await svc.list_sessions(USER)
    assert total == 1 and items[0]["session_id"] == created["session_id"]

    # 他人视角查不到（归属过滤）
    assert await svc.get_session(created["session_id"], "other") is None
    assert await svc.get_session(created["session_id"], USER) is not None

    assert await svc.archive_session(created["session_id"], USER) is True
    assert await svc.archive_session(created["session_id"], USER) is False  # 幂等：已 archived
    _, total_after = await svc.list_sessions(USER)
    assert total_after == 0
    # 软删对用户不可见（数据保留：repo 层仍可查）
    assert await svc.get_session(created["session_id"], USER) is None
    archived = await ChatRepo().find_session(created["session_id"], USER)
    assert archived is not None and archived["status"] == "archived"


async def test_touch_session_first_message_titles(chat_env):
    """首条消息定题：仅标题为空时写入；后续轮不覆盖；message_count 每轮 +2。"""
    repo = ChatRepo()
    session = await repo.create_session(USER)
    sid = session["session_id"]

    await repo.touch_session(sid, title="帮我看看平安银行的因子", preview="回答甲")
    await repo.touch_session(sid, title="第二条不该覆盖", preview="回答乙")

    doc = await repo.find_session(sid, USER)
    assert doc["title"] == "帮我看看平安银行的因子"[:20]
    assert doc["message_count"] == 4
    assert doc["last_message_preview"] == "回答乙"


async def test_append_message_and_replay_order(chat_env):
    """消息 append-only；list_messages 倒序（history 用）、list_all_messages 升序（回放用）。"""
    svc = ChatService()
    session = await svc.create_session(USER)
    sid = session["session_id"]

    await svc.append_message(sid, USER, "user", "问一")
    await svc.append_message(sid, USER, "assistant", "答一", run_meta={"turns": 1})
    await svc.append_message(sid, USER, "user", "问二")

    recent = await ChatRepo().list_messages(sid, limit=2)
    assert [r["content"] for r in recent] == ["问二", "答一"]  # 倒序

    replay = await svc.list_messages(sid)
    assert [r["role"] for r in replay] == ["user", "assistant", "user"]
    assert replay[1]["run_meta"]["turns"] == 1


async def test_record_audit_shape(chat_env):
    """审计文档：digest 50 字截断 / error 500 字截断 / tokens 透传。"""
    svc = ChatService()
    session = await svc.create_session(USER)
    await svc.record_audit(
        USER, session["session_id"], status="failed", question_digest="问" * 80,
        error="错" * 600,
    )
    await svc.record_audit(
        USER, session["session_id"], status="done", model="m1",
        question_digest="问", tokens_used=123,
    )
    # 直接读集合校验形状（repo 无审计列表方法）
    from app.data.storage.mongo.client import get_motor_db
    docs = await get_motor_db()[AUDIT_COLLECTION].find({"user_id": USER}).sort("created_at", 1).to_list(10)
    assert docs[0]["question_digest"] == "问" * 50
    assert docs[0]["error"] == "错" * 500
    assert docs[1]["tokens_used"] == 123
    assert docs[1]["model"] == "m1"
