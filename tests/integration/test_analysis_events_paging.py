"""analysis_events 向前分页扩展集成测试（真实 MongoDB，无 mock）

覆盖：order=desc 最新优先、before_seq 向前翻页、默认升序行为不变。
"""

import uuid

import pytest

from app.services.analysis_events import EVENTS_COLLECTION, load_events, persist_events


def _mk_event(task_id: str, seq: int):
    return {
        "task_id": task_id,
        "seq": seq,
        "ts": 1700000000.0 + seq,
        "phase": "analysts",
        "agent_key": "Market Analyst",
        "event_type": "agent_start",
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
class TestLoadEventsPaging:
    async def test_desc_returns_latest_first(self):
        from app.core.database import get_mongo_db

        task_id = f"evt-pg-{uuid.uuid4().hex[:8]}"
        db = get_mongo_db()
        try:
            await persist_events([_mk_event(task_id, i) for i in range(1, 8)])
            events = await load_events(task_id, order="desc", limit=3)
            assert [e["seq"] for e in events] == [7, 6, 5]
        finally:
            await db[EVENTS_COLLECTION].delete_many({"task_id": task_id})

    async def test_before_seq_pages_backwards(self):
        from app.core.database import get_mongo_db

        task_id = f"evt-pg-{uuid.uuid4().hex[:8]}"
        db = get_mongo_db()
        try:
            await persist_events([_mk_event(task_id, i) for i in range(1, 8)])
            events = await load_events(task_id, order="desc", before_seq=5, limit=3)
            assert [e["seq"] for e in events] == [4, 3, 2]
        finally:
            await db[EVENTS_COLLECTION].delete_many({"task_id": task_id})

    async def test_default_unchanged(self):
        from app.core.database import get_mongo_db

        task_id = f"evt-pg-{uuid.uuid4().hex[:8]}"
        db = get_mongo_db()
        try:
            await persist_events([_mk_event(task_id, i) for i in range(1, 8)])
            events = await load_events(task_id, after_seq=2)
            assert [e["seq"] for e in events] == [3, 4, 5, 6, 7]
        finally:
            await db[EVENTS_COLLECTION].delete_many({"task_id": task_id})
