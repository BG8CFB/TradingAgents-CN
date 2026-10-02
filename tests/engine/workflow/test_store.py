"""seeds / store 测试：本地种子真实加载 + DB 存取全链路（tombstone / builtin / 降级）。

全真 I/O：Mongo 走容器（mongodb_available fixture 不可用时跳过），
种子读真实 config/seeds/*.json。每个 DB 用例前后清集合 + 失效缓存，互不污染。
"""

import copy

import pytest

from app.engine.orchestrator.workflow import seeds, store

pytestmark = pytest.mark.requires_db


# ---------------------------------------------------------------------------
# seeds：本地种子（无 DB 依赖）
# ---------------------------------------------------------------------------


class TestSeeds:
    def test_seed_files_load(self):
        agents = seeds.load_agent_seeds()
        workflows = seeds.load_workflow_seeds()
        assert len(agents) == 14  # phase1×6 + phase2×4 + phase3×4
        assert [w["slug"] for w in workflows] == ["default-4stage"]

    def test_seed_phases_and_order(self):
        agents = seeds.load_agent_seeds()
        phases = [a["phase"] for a in agents]
        assert phases == sorted(phases)  # 按 phase 分组
        assert phases.count(1) == 6 and phases.count(2) == 4 and phases.count(3) == 4
        # phase1 首条 = financial-news-analyst（YAML 原序）
        assert agents[0]["spec"]["slug"] == "financial-news-analyst"

    def test_seed_spec_has_required_fields(self):
        for entry in seeds.load_agent_seeds():
            spec = entry["spec"]
            assert spec.get("slug") and spec.get("name") and spec.get("roleDefinition"), spec.get("slug")

    def test_agent_seed_by_slug(self):
        by_slug = seeds.agent_seed_by_slug()
        assert by_slug["market-analyst"]["phase"] == 1
        assert by_slug["risk-manager"]["phase"] == 3
        assert "ghost" not in by_slug

    def test_spec_hash_stable_and_order_sensitive(self):
        spec = {"b": 2, "a": 1}
        assert seeds.agent_spec_hash(spec) == seeds.agent_spec_hash({"a": 1, "b": 2})  # 键序无关
        assert seeds.agent_spec_hash(spec) != seeds.agent_spec_hash({"a": 1, "b": 3})  # 内容敏感


# ---------------------------------------------------------------------------
# store：DB 存取（真实 Mongo，测试库）
# ---------------------------------------------------------------------------


@pytest.fixture
def clean_store(mongodb_available):
    """每个用例独占集合：用例前清空 + 失效缓存，用例后同样清理。"""
    store.invalidate_store_cache()
    db = store._db()
    db[store.AGENT_SPECS_COLLECTION].delete_many({})
    db[store.WORKFLOW_SPECS_COLLECTION].delete_many({})
    store.invalidate_store_cache()
    yield store
    db[store.AGENT_SPECS_COLLECTION].delete_many({})
    db[store.WORKFLOW_SPECS_COLLECTION].delete_many({})
    store.invalidate_store_cache()


def _seed_all_agents(store_mod) -> None:
    """按种子序全部注入（seeder 的空库路径）。"""
    for pos, entry in enumerate(seeds.load_agent_seeds()):
        store_mod.upsert_agent_spec_from_seed(entry, pos)


class TestAgentSpecsStore:
    def test_empty_collection_falls_back_to_seed(self, clean_store):
        specs = store.list_agent_specs()
        assert len(specs) == 14  # 空集合 → 种子降级（只读视图）

    def test_seed_roundtrip_via_db(self, clean_store):
        _seed_all_agents(store)
        specs = store.list_agent_specs()
        assert len(specs) == 14
        assert [s["slug"] for s in specs] == [e["spec"]["slug"] for e in seeds.load_agent_seeds()]
        # 单条读取
        market = store.get_agent_spec("market-analyst")
        assert market["slug"] == "market-analyst" and market["roleDefinition"]

    def test_position_respects_payload_order(self, clean_store):
        _seed_all_agents(store)
        specs = store.list_agent_specs(phase=1)
        original = [s["slug"] for s in specs]
        reordered = list(reversed(copy.deepcopy(specs)))
        store.replace_phase_agent_specs(1, reordered)
        assert [s["slug"] for s in store.list_agent_specs(phase=1)] == list(reversed(original))

    def test_unchanged_builtin_stays_builtin(self, clean_store):
        _seed_all_agents(store)
        phase1 = copy.deepcopy(store.list_agent_specs(phase=1))
        store.replace_phase_agent_specs(1, phase1)  # 原样写回
        doc = store._db()[store.AGENT_SPECS_COLLECTION].find_one({"_id": "market-analyst"})
        assert doc["builtin"] is True
        assert doc["deleted"] is False

    def test_modified_entry_becomes_user_version(self, clean_store):
        _seed_all_agents(store)
        phase1 = copy.deepcopy(store.list_agent_specs(phase=1))
        for entry in phase1:
            if entry["slug"] == "market-analyst":
                entry["roleDefinition"] = "用户自定义提示词"
        store.replace_phase_agent_specs(1, phase1)
        doc = store._db()[store.AGENT_SPECS_COLLECTION].find_one({"_id": "market-analyst"})
        assert doc["builtin"] is False
        assert doc["spec"]["roleDefinition"] == "用户自定义提示词"
        # 用户版本不被 seeder 覆盖
        action = store.upsert_agent_spec_from_seed(
            next(e for e in seeds.load_agent_seeds() if e["spec"]["slug"] == "market-analyst"), 0
        )
        assert action == "kept"
        assert store.get_agent_spec("market-analyst")["roleDefinition"] == "用户自定义提示词"

    def test_deleted_builtin_tombstoned_not_resurrected(self, clean_store):
        _seed_all_agents(store)
        phase1 = [s for s in copy.deepcopy(store.list_agent_specs(phase=1)) if s["slug"] != "market-analyst"]
        store.replace_phase_agent_specs(1, phase1)  # 删除 market-analyst
        # tombstone 文档存在且读取不可见
        doc = store._db()[store.AGENT_SPECS_COLLECTION].find_one({"_id": "market-analyst"})
        assert doc is not None and doc["deleted"] is True and doc["builtin"] is True
        assert "market-analyst" not in [s["slug"] for s in store.list_agent_specs()]
        assert store.get_agent_spec("market-analyst") is None
        # seeder 不复活
        action = store.upsert_agent_spec_from_seed(
            next(e for e in seeds.load_agent_seeds() if e["spec"]["slug"] == "market-analyst"), 0
        )
        assert action == "tombstoned"
        assert store.get_agent_spec("market-analyst") is None

    def test_tombstone_restored_by_put(self, clean_store):
        _seed_all_agents(store)
        original_phase1 = copy.deepcopy(store.list_agent_specs(phase=1))
        reduced = [s for s in copy.deepcopy(original_phase1) if s["slug"] != "market-analyst"]
        store.replace_phase_agent_specs(1, reduced)
        assert store.get_agent_spec("market-analyst") is None
        # 恢复（payload 重新含种子原内容）
        store.replace_phase_agent_specs(1, original_phase1)
        doc = store._db()[store.AGENT_SPECS_COLLECTION].find_one({"_id": "market-analyst"})
        assert doc["deleted"] is False and doc["builtin"] is True
        assert store.get_agent_spec("market-analyst") is not None

    def test_user_entry_physically_deleted(self, clean_store):
        _seed_all_agents(store)
        phase1 = copy.deepcopy(store.list_agent_specs(phase=1))
        phase1.append(
            {
                "slug": "my-custom-analyst",
                "name": "自定义",
                "roleDefinition": "提示词",
                "description": "my-custom-analyst",
                "data_tools": [],
            }
        )
        store.replace_phase_agent_specs(1, phase1)
        assert store.get_agent_spec("my-custom-analyst") is not None
        # 再删除（非种子条目 → 物理删除，无 tombstone）
        store.replace_phase_agent_specs(1, [s for s in phase1 if s["slug"] != "my-custom-analyst"])
        coll = store._db()[store.AGENT_SPECS_COLLECTION]
        assert coll.find_one({"_id": "my-custom-analyst"}) is None
        assert store.get_agent_spec("my-custom-analyst") is None

    def test_builtin_hash_upgrade(self, clean_store):
        _seed_all_agents(store)
        coll = store._db()[store.AGENT_SPECS_COLLECTION]
        # 模拟软件升级：DB 中种子 hash 落后（内容改旧），新种子内容不同
        coll.update_one({"_id": "market-analyst"}, {"$set": {"seed_hash": "sha256:old"}})
        store.invalidate_store_cache()
        seed_entry = next(e for e in seeds.load_agent_seeds() if e["spec"]["slug"] == "market-analyst")
        action = store.upsert_agent_spec_from_seed(seed_entry, 0)
        assert action == "upgraded"
        assert store.get_agent_spec("market-analyst")["roleDefinition"] == seed_entry["spec"]["roleDefinition"]

    def test_unchanged_seed_action_kept(self, clean_store):
        _seed_all_agents(store)
        seed_entry = next(e for e in seeds.load_agent_seeds() if e["spec"]["slug"] == "bear-researcher")
        assert store.upsert_agent_spec_from_seed(seed_entry, 6) == "kept"

    def test_phase_filter(self, clean_store):
        _seed_all_agents(store)
        assert len(store.list_agent_specs(phase=1)) == 6
        assert len(store.list_agent_specs(phase=2)) == 4
        assert len(store.list_agent_specs(phase=3)) == 4
        assert len(store.list_agent_specs(phase=4)) == 0


class TestWorkflowSpecsStore:
    def test_empty_falls_back_to_seed(self, clean_store):
        assert store.get_workflow_spec("default-4stage") is not None
        assert store.get_workflow_spec("ghost") is None

    def test_seed_roundtrip(self, clean_store):
        seed_spec = seeds.load_workflow_seeds()[0]
        assert store.upsert_workflow_spec_from_seed(seed_spec) == "inserted"
        loaded = store.get_workflow_spec("default-4stage")
        assert loaded["slug"] == "default-4stage"
        assert [s["id"] for s in loaded["stages"]] == [
            "analysts",
            "research_debate",
            "trader",
            "risk_debate",
            "summary",
        ]

    def test_user_modified_workflow_kept(self, clean_store):
        seed_spec = seeds.load_workflow_seeds()[0]
        store.upsert_workflow_spec_from_seed(seed_spec)
        # 用户编辑（builtin=false）
        coll = store._db()[store.WORKFLOW_SPECS_COLLECTION]
        modified = copy.deepcopy(seed_spec)
        modified["name"] = "我的工作流"
        coll.update_one({"_id": "default-4stage"}, {"$set": {"builtin": False, "spec": modified}})
        store.invalidate_store_cache()
        assert store.upsert_workflow_spec_from_seed(seed_spec) == "kept"
        assert store.get_workflow_spec("default-4stage")["name"] == "我的工作流"

    def test_absent_after_injected(self, clean_store):
        store.upsert_workflow_spec_from_seed(seeds.load_workflow_seeds()[0])
        assert store.get_workflow_spec("not-exist") is None
