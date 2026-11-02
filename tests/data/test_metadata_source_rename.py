"""source → data_source 命名迁移（组 7 窗口 A）兼容行为测试。

覆盖三件事（真实 I/O，SimulatedMongoDB 注入）：
1. 读侧双键投影：legacy 只有 source 的文档读回补 data_source；新写只有
   data_source 的文档读回补 source（原键保留不删）；
2. 写侧 legacy 就地升级：update/upsert 命中只有 source 的旧文档时不另插
   新文档，而是补 data_source 双键并存；
3. 迁移脚本幂等：scripts/rename_metadata_source_field.py 对三集合补写
   data_source=source，重复执行零改动，dry-run 不写入。
"""

import importlib.util
from pathlib import Path

import pytest


def _load_rename_script():
    """以文件路径加载 scripts/rename_metadata_source_field.py（非包内模块）。"""
    path = Path(__file__).resolve().parents[2] / "scripts" / "rename_metadata_source_field.py"
    spec = importlib.util.spec_from_file_location("rename_metadata_source_field", path)
    module = importlib.util.module_from_spec(spec)
    # 模块内有 sys.path.insert 与 DEBUG 环境变量兜底，重复执行无副作用
    spec.loader.exec_module(module)
    return module


class TestDualKeyReadProjection:
    """读侧双键投影。"""

    @pytest.mark.asyncio
    async def test_legacy_checkpoint_doc_read_back_with_data_source(self, inject_sim_db, metadata_repo):
        """只有 legacy source 的存量检查点：读回补 data_source，source 保留。"""
        await inject_sim_db["sync_checkpoints"].insert_one({
            "market": "CN", "domain": "daily_quotes", "source": "tushare",
            "last_sync_date": "2026-06-19", "last_sync_time": "2026-06-19T10:00:00+00:00",
        })

        doc = await metadata_repo.get_checkpoint("CN", "daily_quotes", "tushare")
        assert doc is not None
        assert doc["data_source"] == "tushare"
        assert doc["source"] == "tushare"

        all_docs = await metadata_repo.get_all_checkpoints("CN")
        assert all_docs[0]["data_source"] == "tushare"
        assert all_docs[0]["source"] == "tushare"

    @pytest.mark.asyncio
    async def test_new_write_checkpoint_read_back_with_source_alias(self, inject_sim_db, metadata_repo):
        """新写入（data_source 键）的检查点：读回补 source 别名，新旧消费方都能工作。"""
        await metadata_repo.update_checkpoint(
            market="CN", domain="daily_quotes", source="akshare",
            last_sync_date="2026-06-19", record_count=5,
        )

        raw = await inject_sim_db["sync_checkpoints"].find_one({"market": "CN"})
        assert raw["data_source"] == "akshare"

        doc = await metadata_repo.get_checkpoint("CN", "daily_quotes", "akshare")
        assert doc["data_source"] == "akshare"
        assert doc["source"] == "akshare"

    @pytest.mark.asyncio
    async def test_legacy_health_doc_upsert_upgrades_in_place(self, inject_sim_db, metadata_repo):
        """upsert_health 命中只有 source 的旧健康文档：就地补双键，不产生重复文档。"""
        await inject_sim_db["source_health"].insert_one({
            "market": "CN", "domain": "daily_quotes", "source": "tushare",
            "circuit_state": "open",
        })

        await metadata_repo.upsert_health(
            "CN", "tushare", "daily_quotes", {"circuit_state": "closed"}
        )

        count = await inject_sim_db["source_health"].count_documents({})
        assert count == 1, "legacy 健康文档应就地升级，不应另插新文档"
        doc = await metadata_repo.get_health("CN", "tushare", "daily_quotes")
        assert doc["circuit_state"] == "closed"
        assert doc["data_source"] == "tushare"
        assert doc["source"] == "tushare"

    @pytest.mark.asyncio
    async def test_insert_event_normalizes_legacy_source_key(self, inject_sim_db, metadata_repo):
        """尚未迁移的写入方传 legacy source 键：insert_event 收口补 data_source。"""
        await metadata_repo.insert_event({
            "event_type": "DEDUPE_MIGRATION", "market": "CN",
            "domain": "all", "source": "migration",
        })

        events = await metadata_repo.get_events("CN", limit=10)
        assert events[0]["data_source"] == "migration"
        assert events[0]["source"] == "migration"

    @pytest.mark.asyncio
    async def test_update_checkpoint_legacy_doc_upgrades_in_place(self, inject_sim_db, metadata_repo):
        """update_checkpoint 命中只有 source 的旧检查点：就地补双键，不产生重复文档。"""
        await inject_sim_db["sync_checkpoints"].insert_one({
            "market": "HK", "domain": "basic_info", "source": "akshare_hk",
            "last_sync_date": "2026-01-01", "last_sync_time": "2026-01-01T00:00:00+00:00",
        })

        await metadata_repo.update_checkpoint(
            market="HK", domain="basic_info", source="akshare_hk",
            last_sync_date="2026-06-19", record_count=50,
        )

        count = await inject_sim_db["sync_checkpoints"].count_documents({})
        assert count == 1, "legacy 检查点应就地升级，不应另插新文档"
        doc = await metadata_repo.get_checkpoint("HK", "basic_info", "akshare_hk")
        assert doc["data_source"] == "akshare_hk"
        assert doc["last_sync_date"] == "2026-06-19"


class TestRenameMigrationScript:
    """scripts/rename_metadata_source_field.py 幂等迁移。"""

    @pytest.mark.asyncio
    async def test_rename_idempotent_and_keeps_legacy_key(self, inject_sim_db):
        script = _load_rename_script()
        for coll, docs in {
            "sync_checkpoints": [
                {"market": "CN", "domain": "daily_quotes", "source": "tushare"},
                {"market": "CN", "domain": "basic_info", "source": "akshare"},
            ],
            "sync_events": [
                {"market": "CN", "event_type": "SYNC_SUCCESS", "domain": "all", "source": "migration"},
            ],
            "source_health": [
                {"market": "HK", "domain": "daily_quotes", "source": "yfinance"},
            ],
        }.items():
            await inject_sim_db[coll].insert_many(docs)

        stats = await script.rename_source_field(inject_sim_db)
        assert stats == {"sync_checkpoints": 2, "sync_events": 1, "source_health": 1}

        for coll, expected in {
            "sync_checkpoints": ("tushare", "akshare"),
            "sync_events": ("migration",),
            "source_health": ("yfinance",),
        }.items():
            docs = await inject_sim_db[coll].find({}).to_list()
            for doc in docs:
                assert doc["data_source"] in expected
                assert doc["source"] == doc["data_source"], "legacy source 键必须保留"

        # 幂等：二次运行无待迁移文档
        stats_again = await script.rename_source_field(inject_sim_db)
        assert all(v == 0 for v in stats_again.values())

    @pytest.mark.asyncio
    async def test_rename_dry_run_does_not_write(self, inject_sim_db):
        script = _load_rename_script()
        await inject_sim_db["sync_checkpoints"].insert_one({
            "market": "CN", "domain": "daily_quotes", "source": "tushare",
        })

        stats = await script.rename_source_field(inject_sim_db, dry_run=True)
        assert stats["sync_checkpoints"] == 1

        doc = await inject_sim_db["sync_checkpoints"].find_one({})
        assert "data_source" not in doc, "dry-run 不应写入"
