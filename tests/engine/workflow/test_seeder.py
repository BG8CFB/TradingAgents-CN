"""seeder 测试：幂等注入 / 首次迁移（YAML → DB 保留用户修改）/ tombstone 不复活。

隔离手段（全真实 I/O，无 mock）：临时目录组装 config 布局
    tmp/config/seeds/      （真实种子的文件副本）
    tmp/config/agents/     （从种子 JSON 合成的旧版 YAML + 定向修改）
    tmp/config/workflows/  （从种子 JSON 合成的 default.yaml + 定向修改）
AGENT_CONFIG_DIR 指向 tmp/config/agents 使探测链落到临时布局，测后还原。

仓库 YAML 已退役（2026-09 工作流通用化）：迁移逻辑服务已部署环境（如 NAS
config 卷中仍存留 YAML），测试用种子 JSON 合成同形状的 legacy 布局覆盖该路径。
"""

import json
import os
import shutil
from pathlib import Path

import pytest

from app.engine.orchestrator.workflow import seeds, seeder, store

pytestmark = pytest.mark.requires_db

REAL_SEEDS_DIR = seeds.locate_seeds_dir()
TMP_ROOT = Path(__file__).resolve().parents[3] / ".ai_temp" / "seeder_test"


def _write_legacy_layout(cfg: Path) -> None:
    """从种子 JSON 合成旧 YAML 存放（phase1-3 customModes + default.yaml）。

    形状与退役前的真实文件一致且内容与种子逐条相同（幂等用例期望 builtin=true
    直插；迁移用例再做定向修改分叉出用户版本路径）。
    """
    import yaml

    agents_payload = json.loads((REAL_SEEDS_DIR / "agents.json").read_text(encoding="utf-8"))
    agents_dir = cfg / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    for phase in (1, 2, 3):
        modes = [a["spec"] for a in agents_payload["agents"] if a.get("phase") == phase]
        path = agents_dir / f"phase{phase}_agents_config.yaml"
        path.write_text(yaml.safe_dump({"customModes": modes}, allow_unicode=True), encoding="utf-8")

    wf_payload = json.loads((REAL_SEEDS_DIR / "workflows.json").read_text(encoding="utf-8"))
    wf_dir = cfg / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    (wf_dir / "default.yaml").write_text(
        yaml.safe_dump(wf_payload["workflows"][0], allow_unicode=True), encoding="utf-8"
    )


@pytest.fixture
def migrated_env(mongodb_available):
    """临时 config 布局 + 空 DB 集合。yield 临时目录，用例可继续修改其中文件。"""
    if TMP_ROOT.exists():
        shutil.rmtree(TMP_ROOT)
    cfg = TMP_ROOT / "config"
    (cfg / "seeds").mkdir(parents=True)
    for name in ("agents.json", "workflows.json"):
        shutil.copy2(REAL_SEEDS_DIR / name, cfg / "seeds" / name)
    _write_legacy_layout(cfg)

    seeds._cache.clear()
    store.invalidate_store_cache()
    db = store._db()
    db[store.AGENT_SPECS_COLLECTION].delete_many({})
    db[store.WORKFLOW_SPECS_COLLECTION].delete_many({})

    old_env = os.environ.get("AGENT_CONFIG_DIR")
    os.environ["AGENT_CONFIG_DIR"] = str(cfg / "agents")
    try:
        yield cfg
    finally:
        if old_env is None:
            os.environ.pop("AGENT_CONFIG_DIR", None)
        else:
            os.environ["AGENT_CONFIG_DIR"] = old_env
        db[store.AGENT_SPECS_COLLECTION].delete_many({})
        db[store.WORKFLOW_SPECS_COLLECTION].delete_many({})
        store.invalidate_store_cache()
        seeds._cache.clear()
        shutil.rmtree(TMP_ROOT, ignore_errors=True)


def _rewrite_yaml_phase1(cfg: Path, market_prompt: str, drop_slug: str, extra_entry: dict | None) -> None:
    """对临时布局的 phase1 YAML 定向修改（用户改 prompt / 删条目 / 加条目）。"""
    import yaml

    path = cfg / "agents" / "phase1_agents_config.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    modes = [m for m in (data.get("customModes") or []) if m.get("slug") != drop_slug]
    for m in modes:
        if m.get("slug") == "market-analyst":
            m["roleDefinition"] = market_prompt
    if extra_entry:
        modes.append(extra_entry)
    path.write_text(yaml.safe_dump({"customModes": modes}, allow_unicode=True), encoding="utf-8")


class TestSeederIdempotent:
    def test_sync_all_then_resync_kept(self, migrated_env):
        stats = seeder.sync_all()
        assert len(store.list_agent_specs()) == 14
        assert store.get_workflow_spec("default-4stage") is not None
        # 幂等：第二遍全部 kept（无插入/升级/tombstone 动作）
        stats2 = seeder.sync_all()
        assert stats2["agents"] == {"inserted": 0, "upgraded": 0, "kept": 14, "tombstoned": 0}
        assert stats2["workflows"] == {"inserted": 0, "upgraded": 0, "kept": 1, "tombstoned": 0}
        _ = stats

    def test_builtin_upgrade_on_seed_hash_drift(self, migrated_env):
        seeder.sync_all()
        coll = store._db()[store.AGENT_SPECS_COLLECTION]
        coll.update_one({"_id": "market-analyst"}, {"$set": {"seed_hash": "sha256:stale"}})
        store.invalidate_store_cache()
        stats = seeder.sync_all()
        assert stats["agents"]["upgraded"] == 1


class TestFirstTimeMigration:
    def test_user_modifications_preserved(self, migrated_env):
        _rewrite_yaml_phase1(
            migrated_env,
            market_prompt="用户改过的提示词",
            drop_slug="social-media-analyst",
            extra_entry={
                "slug": "my-own-analyst",
                "name": "自建分析师",
                "roleDefinition": "自建提示词",
                "description": "my-own-analyst",
            },
        )
        stats = seeder.sync_all()

        # 改过的内置条目：用户版本（builtin=false，内容保留）
        doc = store._db()[store.AGENT_SPECS_COLLECTION].find_one({"_id": "market-analyst"})
        assert doc["builtin"] is False
        assert doc["spec"]["roleDefinition"] == "用户改过的提示词"
        assert doc["seed_hash"]  # 记录种子版本

        # 删掉的内置条目：tombstone，读取不可见
        doc = store._db()[store.AGENT_SPECS_COLLECTION].find_one({"_id": "social-media-analyst"})
        assert doc is not None and doc["deleted"] is True
        assert store.get_agent_spec("social-media-analyst") is None

        # 自建条目：builtin=false 入库
        assert store.get_agent_spec("my-own-analyst") is not None

        # 未动过的条目：builtin=true
        doc = store._db()[store.AGENT_SPECS_COLLECTION].find_one({"_id": "bear-researcher"})
        assert doc["builtin"] is True and doc["deleted"] is False

        assert len(store.list_agent_specs()) == 14  # 14 种子 - 1 删 + 1 自建

        # 再同步：用户版本与 tombstone 都不被种子覆盖
        stats2 = seeder.sync_all()
        assert stats2["agents"]["kept"] >= 13
        assert store.get_agent_spec("social-media-analyst") is None
        assert store.get_agent_spec("market-analyst")["roleDefinition"] == "用户改过的提示词"
        _ = stats

    def test_workflow_user_version_preserved(self, migrated_env):
        import yaml

        path = migrated_env / "workflows" / "default.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        data["name"] = "我的自定义工作流"
        path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")

        seeder.sync_all()
        spec = store.get_workflow_spec("default-4stage")
        assert spec["name"] == "我的自定义工作流"
        coll = store._db()[store.WORKFLOW_SPECS_COLLECTION]
        assert coll.find_one({"_id": "default-4stage"})["builtin"] is False

        # 再同步不被覆盖
        seeder.sync_all()
        assert store.get_workflow_spec("default-4stage")["name"] == "我的自定义工作流"
