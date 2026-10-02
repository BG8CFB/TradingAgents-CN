"""InsightService 非 LLM 行为：设置默认值/覆盖、配额边界、失败审计。

LLM 真调用在 test_insight_service_ai.py（-m ai）。本文件全部走真实
库读写，失败用例走「因子取不到」真实分支（不 mock LLM）。
"""

import pytest

pytestmark = pytest.mark.requires_db

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name
from app.services.screening.insight_service import (
    DEFAULT_INSIGHT_SYSTEM_PROMPT, ScreeningInsightService,
)

QUOTA_USER = "insight_quota_user"


async def _cleanup(db):
    await db[get_collection_name("screening_insights", "CN")].delete_many(
        {"user_id": QUOTA_USER})
    await db.system_configs.delete_many({"config_name": "insight_test_cfg"})


async def test_settings_defaults_and_override(real_mongo_db):
    """无 system_settings 时返回内置默认值；写入后按库内值覆盖。"""
    db = get_motor_db()
    await _cleanup(db)
    svc = ScreeningInsightService()

    # 默认值：开关关、配额 10、模型回落 analyst、提示词为内置默认
    defaults = await svc.get_settings()
    assert defaults["daily_enabled"] is False
    assert defaults["manual_daily_limit"] == 10
    assert defaults["model"] is None
    assert defaults["prompt"] == DEFAULT_INSIGHT_SYSTEM_PROMPT

    # 库内覆盖（get_system_config 取 is_active 且 version 最大的一条）
    await db.system_configs.insert_one({
        "config_name": "insight_test_cfg", "config_type": "system",
        "version": 99999, "is_active": True, "llm_configs": [],
        "system_settings": {
            "screening_daily_insight_enabled": True,
            "screening_manual_insight_daily_limit": 3,
            "screening_insight_model": "test-model",
            "screening_insight_prompt": "自定义提示词",
        },
    })
    overridden = await svc.get_settings()
    assert overridden["daily_enabled"] is True
    assert overridden["manual_daily_limit"] == 3
    assert overridden["model"] == "test-model"
    assert overridden["prompt"] == "自定义提示词"

    await _cleanup(db)


async def test_quota_boundary(real_mongo_db):
    """配额只数 status=done：1 done + 1 failed → 剩余 9。"""
    import datetime
    from app.utils.timezone import now_tz
    db = get_motor_db()
    await _cleanup(db)
    today = now_tz().strftime("%Y-%m-%d")
    coll = db[get_collection_name("screening_insights", "CN")]
    base = {"user_id": QUOTA_USER, "trigger": "manual", "symbols": ["000001"],
            "insights": {}, "trade_date": None}
    await coll.insert_one({**base, "created_at": f"{today}T09:00:00+08:00",
                           "status": "done"})
    await coll.insert_one({**base, "created_at": f"{today}T10:00:00+08:00",
                           "status": "failed", "error": "x"})
    # 隔日 done 不计入今日
    yesterday = (now_tz() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    await coll.insert_one({**base,
                           "created_at": f"{yesterday}T09:00:00+08:00",
                           "status": "done"})

    remaining = await ScreeningInsightService().quota_remaining(QUOTA_USER)
    assert remaining == 9

    await _cleanup(db)


async def test_generate_manual_records_audit_even_on_failure(real_mongo_db):
    """因子取不到 → 真实失败分支：落 failed 审计、向上抛错、不扣配额。"""
    db = get_motor_db()
    await _cleanup(db)
    svc = ScreeningInsightService()
    fail_user = "insight_fail_user"
    await db[get_collection_name("screening_insights", "CN")].delete_many(
        {"user_id": fail_user})

    with pytest.raises(ValueError):
        # TESTNOSUCH 在 factor_scores 中不存在 → _fetch_factor_rows 返回空
        await svc.generate_manual(["TESTNOSUCH"], user_id=fail_user,
                                  strategy_id="volume_breakout",
                                  conditions_digest="test")

    audit = await db[get_collection_name("screening_insights", "CN")].find_one(
        {"user_id": fail_user, "status": "failed"})
    assert audit is not None
    assert audit["symbols"] == ["TESTNOSUCH"]
    assert audit["strategy_id"] == "volume_breakout"
    assert "无这些 symbol" in audit["error"]

    # 失败不扣配额
    remaining = await svc.quota_remaining(fail_user)
    assert remaining == 10

    await db[get_collection_name("screening_insights", "CN")].delete_many(
        {"user_id": fail_user})
    await _cleanup(db)
