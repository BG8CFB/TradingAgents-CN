"""analysis_events 集成测试（真实 MongoDB，无 mock）

覆盖：事件落库/回放读取（分页与过滤）、活动 sink 注册表的 running 校验
（WS 上行 user_message 的门禁）、release 清理。
"""

import uuid

import pytest

from app.services.analysis_events import (
    EVENTS_COLLECTION,
    create_event_sink,
    persist_events,
    enqueue_user_message,
    get_active_sink,
    is_agent_running,
    load_events,
    release_event_sink,
    running_agents,
)


def _mk_event(task_id: str, seq: int, agent_key: str, event_type: str):
    return {
        "task_id": task_id,
        "seq": seq,
        "ts": 1700000000.0 + seq,
        "phase": "analysts",
        "agent_key": agent_key,
        "event_type": event_type,
        "payload": {"n": seq},
    }


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
class TestAnalysisEventsMongo:
    async def test_persist_and_load_roundtrip(self):
        from app.core.database import get_mongo_db

        task_id = f"evt-it-{uuid.uuid4().hex[:8]}"
        db = get_mongo_db()
        try:
            from app.services.analysis_events import persist_events

            await persist_events([
                _mk_event(task_id, 1, "Market Analyst", "agent_start"),
                _mk_event(task_id, 2, "Market Analyst", "tool_call"),
                _mk_event(task_id, 3, "News Analyst", "agent_start"),
            ])

            events = await load_events(task_id)
            assert [e["seq"] for e in events] == [1, 2, 3]

            # 按 agent 过滤
            only_news = await load_events(task_id, agent_key="News Analyst")
            assert len(only_news) == 1 and only_news[0]["seq"] == 3

            # 增量拉取
            tail = await load_events(task_id, after_seq=2)
            assert [e["seq"] for e in tail] == [3]
        finally:
            await db[EVENTS_COLLECTION].delete_many({"task_id": task_id})

    async def test_load_empty_task(self):
        # 与上一用例合并断言：motor 客户端绑定首个事件循环，
        # pytest-asyncio 每用例新循环会导致跨循环游标报错
        events = await load_events(f"no-such-{uuid.uuid4().hex[:8]}")
        assert events == []
        # 清理本用例数据（同循环内完成）
        from app.core.database import get_mongo_db

        task_id = f"evt-empty-{uuid.uuid4().hex[:8]}"
        await persist_events([_mk_event(task_id, 1, "X", "agent_start")])
        assert len(await load_events(task_id)) == 1
        await get_mongo_db()[EVENTS_COLLECTION].delete_many({"task_id": task_id})


@pytest.mark.requires_db
class TestActiveSinkRegistry:
    def test_running_gate_and_release(self):
        task_id = f"evt-sink-{uuid.uuid4().hex[:8]}"
        sink = create_event_sink(task_id, server_loop=None)
        try:
            assert get_active_sink(task_id) is sink

            sink.mark_running("Market Analyst")
            assert is_agent_running(task_id, "Market Analyst")
            assert running_agents(task_id) == ["Market Analyst"]

            # running 的 agent 可入队
            assert enqueue_user_message(task_id, "Market Analyst", "请关注资金面") is True
            from app.llm.message_queue import message_queues

            msgs = message_queues.drain(task_id, "Market Analyst")
            assert len(msgs) == 1 and msgs[0].text == "请关注资金面"

            sink.mark_completed("Market Analyst")
            assert not is_agent_running(task_id, "Market Analyst")
            # 完成后拒绝入队（用户消息门禁核心约束）
            assert enqueue_user_message(task_id, "Market Analyst", "late") is False
        finally:
            release_event_sink(task_id, server_loop=None)

        assert get_active_sink(task_id) is None
        assert running_agents(task_id) == []
