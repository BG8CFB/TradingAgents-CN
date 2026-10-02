"""conversation_runner 单元层测试 — 多轮 history 构造 / 运行注册表 / 会话锁（真实 asyncio 任务）。"""
import asyncio

import pytest

pytestmark = pytest.mark.requires_db

from app.data.storage.mongo.repositories.chat_repo import (
    MESSAGES_COLLECTION,
    SESSIONS_COLLECTION,
    ChatRepo,
)
from app.llm.core.types import Role
from app.services.chat import conversation_runner as runner


async def test_build_history_recent_and_ascending(real_mongo_db):
    """history = 最近 20 条、时间升序、role 映射正确；窗口外旧消息被切掉。

    真实 MongoDB：list_messages 依赖 created_at 真实排序（模拟库 sort 为 no-op）。
    """
    from app.data.storage.mongo.client import get_motor_db

    sid = (await ChatRepo().create_session("u1"))["session_id"]
    coll = get_motor_db()[MESSAGES_COLLECTION]
    # 1 条窗口外旧消息 + 22 条窗口内消息（11 轮问答，严格递增时间戳）
    docs = [{"session_id": sid, "user_id": "u1", "role": "assistant",
             "content": "很久以前", "created_at": "2020-01-01T00:00:00"}]
    contents = []
    for i in range(11):
        for role, prefix in (("user", "问"), ("assistant", "答")):
            content = f"{prefix}{i}"
            contents.append(content)
            docs.append({
                "session_id": sid, "user_id": "u1", "role": role,
                "content": content, "created_at": f"2026-09-10T10:{i:02d}:{contents.index(content):02d}",
            })
    await coll.insert_many(docs)

    history = await runner._build_history(sid)
    assert len(history) == 20  # 23 条中取最近 20 条
    assert [m.content for m in history] == contents[2:]  # 升序，最旧 2 条被切
    assert history[0].role == Role.USER
    assert history[1].role == Role.ASSISTANT

    await coll.delete_many({"session_id": sid})
    await get_motor_db()[SESSIONS_COLLECTION].delete_one({"session_id": sid})


async def test_run_registry_start_stop_roundtrip():
    """start_run 注册 → is_running True → stop_run cancel → 出表；未注册 stop 返回 False。"""
    async def slow():
        await asyncio.sleep(30)

    run_id = "run_registry_test"
    task = runner.start_run(run_id, slow())
    assert runner.is_running(run_id) is True
    assert runner.stop_run(run_id) is True
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0)  # 让 done_callback 出表
    assert runner.is_running(run_id) is False
    assert runner.stop_run("run_never_exists") is False


async def test_run_registry_auto_pop_on_complete():
    """任务正常结束后自动出表。"""
    async def quick():
        return 42

    run_id = "run_quick_test"
    task = runner.start_run(run_id, quick())
    assert await task == 42
    await asyncio.sleep(0)
    assert runner.is_running(run_id) is False


def test_get_session_lock_singleton_per_session():
    """同一 session 复用同一把锁；不同 session 各自独立。"""
    lock1 = runner.get_session_lock("sess_a")
    lock2 = runner.get_session_lock("sess_a")
    lock_b = runner.get_session_lock("sess_b")
    assert lock1 is lock2
    assert lock1 is not lock_b
