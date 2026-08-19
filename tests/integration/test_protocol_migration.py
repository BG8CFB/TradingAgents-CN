"""模型级 protocol → 厂家级迁移测试（真实 MongoDB，无 mock）

覆盖 migrate_model_protocol_to_providers：
- 模型级 protocol 回填到 protocol 为空的厂家文档
- 已有厂家 protocol 不被覆盖
- 回填后模型配置内嵌文档的 protocol 字段被清除（幂等）
"""

import uuid

import pytest

from app.services.config.llm_service import LLMService


@pytest.fixture(autouse=True)
async def _real_mongo(mongodb_available):
    """每用例重建真实 MongoDB 客户端（motor 绑定事件循环，见 test_analysis_events）"""
    import app.core.database as db_mod
    from app.core.database import close_database, init_database

    await init_database()
    yield
    await close_database()
    db_mod.mongo_db = None
    db_mod.mongo_client = None


@pytest.mark.integration
@pytest.mark.requires_db
class TestProtocolMigration:
    async def test_backfill_and_cleanup(self):
        from app.core.database import get_mongo_db

        db = get_mongo_db()
        tag = uuid.uuid4().hex[:8]
        # 厂家 A：protocol 为空（应被回填 anthropic）；厂家 B：已有 openai（不应被覆盖）
        pa = await db.llm_providers.insert_one({"name": f"mig-a-{tag}", "display_name": "A", "is_active": True})
        pb = await db.llm_providers.insert_one(
            {"name": f"mig-b-{tag}", "display_name": "B", "is_active": True, "protocol": "openai"}
        )
        sc = await db.system_configs.insert_one({
            "is_active": True,
            "version": 1,
            "llm_configs": [
                {"provider": f"mig-a-{tag}", "model_name": "m1", "protocol": "anthropic"},
                {"provider": f"mig-b-{tag}", "model_name": "m2", "protocol": "anthropic"},
                {"provider": f"mig-a-{tag}", "model_name": "m3"},  # 无 protocol
            ],
        })
        try:
            result = await LLMService().migrate_model_protocol_to_providers()
            assert result["migrated_providers"] >= 1

            doc_a = await db.llm_providers.find_one({"_id": pa.inserted_id})
            doc_b = await db.llm_providers.find_one({"_id": pb.inserted_id})
            assert doc_a["protocol"] == "anthropic"
            assert doc_b["protocol"] == "openai"  # 已有值不被覆盖

            cfgs = (await db.system_configs.find_one({"_id": sc.inserted_id}))["llm_configs"]
            assert all("protocol" not in c for c in cfgs)

            # 幂等：二次执行无迁移量
            result2 = await LLMService().migrate_model_protocol_to_providers()
            assert result2["migrated_providers"] == 0
        finally:
            await db.llm_providers.delete_many({"name": {"$in": [f"mig-a-{tag}", f"mig-b-{tag}"]}})
            await db.system_configs.delete_one({"_id": sc.inserted_id})
