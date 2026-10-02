"""InsightService 真实 LLM 调用（-m ai；需已配置模型与已种因子数据）。"""

import pytest

pytestmark = [pytest.mark.ai, pytest.mark.requires_db]

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name
from app.services.screening.insight_service import ScreeningInsightService

AI_USER = "insight_ai_user"


async def test_generate_manual_real_call(real_mongo_db, seed_factor_inputs):
    """种 TESTF001 因子 → 单次 LLM 调用 → done 审计 + 配额扣减。"""
    db = get_motor_db()
    coll = db[get_collection_name("screening_insights", "CN")]
    await coll.delete_many({"user_id": AI_USER})

    result = await ScreeningInsightService().generate_manual(
        ["TESTF001"], user_id=AI_USER, strategy_id="volume_breakout")

    assert "TESTF001" in result["insights"]
    assert result["insights"]["TESTF001"]
    assert result["trade_date"] == seed_factor_inputs["dates"][-1]
    assert result["quota_remaining"] == 9

    audit = await coll.find_one({"user_id": AI_USER, "status": "done"})
    assert audit is not None
    assert audit["insights"].get("TESTF001")

    await coll.delete_many({"user_id": AI_USER})
