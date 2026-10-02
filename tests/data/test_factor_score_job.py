"""CNFactorScoreJob 集成测试：种子数据 → execute → factor_scores 落库。"""
import pytest

pytestmark = pytest.mark.requires_db

from app.data.scheduler.jobs.cn import CNFactorScoreJob
from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name


async def test_factor_score_job_writes_output(real_mongo_db, seed_factor_inputs):
    """seed_factor_inputs fixture 来自 tests/data/conftest.py 的共享种子助手。"""
    db = get_motor_db()
    coll = db[get_collection_name("factor_scores", "CN")]
    await coll.delete_many({"symbol": {"$regex": "^TESTF"}})

    job = CNFactorScoreJob()
    job.force_sync = True  # 跳过交易日检查（测试可能落在周末）
    result = await job.execute()

    assert result["status"] == "ok"
    docs = await coll.find({"symbol": {"$regex": "^TESTF"}}).to_list(None)
    assert len(docs) >= 2
    doc = docs[0]
    assert doc["trade_date"]
    assert "score_short_term" in doc and "ret_5d" in doc
    assert doc["data_source"] == "computed"

    await coll.delete_many({"symbol": {"$regex": "^TESTF"}})
