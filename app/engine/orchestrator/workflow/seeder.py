"""启动种子同步（seeder）：幂等地把本地 JSON 种子注入 DB。

同步规则（每次启动执行，全部幂等）：
- 空集合 → 全量注入（builtin=true）
- builtin 且种子 hash 落后 → 覆盖升级（软件升级带来的新种子内容）
- builtin=false（用户修改过或用户自建）→ 不动
- tombstone（deleted=true）→ 不复活，仅同步最新种子内容供「恢复默认」

首次迁移（一次性，仅当 DB 空且存在旧 YAML 存放）：
- YAML 条目与种子逐条比对：内容一致 → builtin=true；有差异 → 保留 YAML 用户版本
  （builtin=false，seed_hash 记录种子版本供升级提示）
- 种子有而 YAML 没有（用户已删的内置条目）→ tombstone
- YAML 独有条目（用户自建）→ builtin=false 入库

容错：Mongo 不可达时抛异常由调用方决定；调用方（lifespan / worker main）选择
不阻断启动——store 读取路径自带种子降级，行为等价。
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from app.engine.orchestrator.workflow import store
from app.engine.orchestrator.workflow.seeds import (
    agent_seed_by_slug,
    agent_spec_hash,
    load_agent_seeds,
    load_workflow_seeds,
    locate_seeds_dir,
)

logger = logging.getLogger(__name__)

# 旧 YAML 存放的剥离键（与 agent_configs 路由的迁移期语义一致；
# YAML 退役后本模块的首次迁移路径自然不再触发）
_LEGACY_KEYS = ("whenToUse", "groups", "source", "initial_task", "tools")


def _locate_legacy_agents_dir() -> Optional[Path]:
    """探测旧 config/agents/（存在即视为未迁移环境）。"""
    candidate = locate_seeds_dir().parent / "agents"
    if (candidate / "phase1_agents_config.yaml").is_file():
        return candidate
    return None


def _load_legacy_yaml_entries() -> Dict[str, tuple]:
    """读旧 phase1-3 YAML 并归一化为 {slug: (phase, entry)}（无 YAML 返回空 dict）。"""
    import yaml

    legacy_dir = _locate_legacy_agents_dir()
    if legacy_dir is None:
        return {}

    entries: Dict[str, tuple] = {}
    for phase in (1, 2, 3):
        path = legacy_dir / f"phase{phase}_agents_config.yaml"
        if not path.is_file():
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for item in data.get("customModes") or []:
            if not isinstance(item, dict) or not item.get("slug"):
                continue
            for key in _LEGACY_KEYS:
                item.pop(key, None)
            entries[item["slug"]] = (phase, item)
    return entries


def _first_time_migrate_agents() -> Optional[Dict[str, int]]:
    """首次迁移：YAML 内容逐条入 DB（保留用户修改）。返回统计；非迁移场景返回 None。"""
    if store.agent_collection_initialized():
        return None
    yaml_entries = _load_legacy_yaml_entries()
    if not yaml_entries:
        return None

    now = datetime.now(timezone.utc)
    coll = store._db()[store.AGENT_SPECS_COLLECTION]
    position_by_phase: Dict[int, int] = {}
    stats = {"inserted_builtin": 0, "inserted_user": 0, "migrated_user_modified": 0, "tombstoned": 0}

    for entry in load_agent_seeds():
        slug = entry["spec"]["slug"]
        pos = position_by_phase.get(entry["phase"], 0)
        position_by_phase[entry["phase"]] = pos + 1
        legacy = yaml_entries.get(slug)
        yaml_entry = legacy[1] if legacy else None
        if yaml_entry is None:
            coll.insert_one(
                {
                    "_id": slug,
                    "phase": entry["phase"],
                    "position": pos,
                    "builtin": True,
                    "seed_hash": agent_spec_hash(entry["spec"]),
                    "deleted": True,
                    "spec": entry["spec"],
                    "created_at": now,
                    "updated_at": now,
                }
            )
            stats["tombstoned"] += 1
        elif agent_spec_hash(yaml_entry) == agent_spec_hash(entry["spec"]):
            coll.insert_one(
                {
                    "_id": slug,
                    "phase": entry["phase"],
                    "position": pos,
                    "builtin": True,
                    "seed_hash": agent_spec_hash(entry["spec"]),
                    "deleted": False,
                    "spec": entry["spec"],
                    "created_at": now,
                    "updated_at": now,
                }
            )
            stats["inserted_builtin"] += 1
        else:
            coll.insert_one(
                {
                    "_id": slug,
                    "phase": entry["phase"],
                    "position": pos,
                    "builtin": False,
                    "seed_hash": agent_spec_hash(entry["spec"]),
                    "deleted": False,
                    "spec": yaml_entry,
                    "created_at": now,
                    "updated_at": now,
                }
            )
            stats["migrated_user_modified"] += 1

    # YAML 独有条目（用户自建）→ builtin=false，position 排在种子之后
    seed_slugs = set(agent_seed_by_slug().keys())
    extra_pos = sum(position_by_phase.values())
    for slug, (phase, yaml_entry) in yaml_entries.items():
        if slug in seed_slugs:
            continue
        coll.insert_one(
            {
                "_id": slug,
                "phase": phase,
                "position": extra_pos,
                "builtin": False,
                "seed_hash": None,
                "deleted": False,
                "spec": yaml_entry,
                "created_at": now,
                "updated_at": now,
            }
        )
        stats["inserted_user"] += 1

    store.invalidate_store_cache()
    logger.info("🌱 [seeder] 首次迁移完成（YAML → agent_specs）: %s", stats)
    return stats


def sync_agent_specs() -> Dict[str, int]:
    """同步 agent_specs（含首次迁移探测）。"""
    migrated = _first_time_migrate_agents()
    if migrated is not None:
        return migrated

    stats = {"inserted": 0, "upgraded": 0, "kept": 0, "tombstoned": 0}
    for pos, entry in enumerate(load_agent_seeds()):
        action = store.upsert_agent_spec_from_seed(entry, pos)
        stats[action] = stats.get(action, 0) + 1
    return stats


def _first_time_migrate_workflows() -> Optional[Dict[str, int]]:
    """首次迁移：default.yaml（若存在且 DB 空）与种子比对入库。"""
    if store.workflow_collection_initialized():
        return None
    yaml_path = locate_seeds_dir().parent / "workflows" / "default.yaml"
    if not yaml_path.is_file():
        return None

    import yaml

    from app.engine.orchestrator.workflow.spec import WorkflowSpec

    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    yaml_spec = WorkflowSpec.model_validate(raw).model_dump(mode="json")
    yaml_hash = agent_spec_hash(yaml_spec)

    now = datetime.now(timezone.utc)
    stats = {"inserted_builtin": 0, "migrated_user_modified": 0, "tombstoned": 0}
    coll = store._db()[store.WORKFLOW_SPECS_COLLECTION]

    yaml_matched = False
    for seed_spec in load_workflow_seeds():
        if yaml_spec["slug"] != seed_spec["slug"]:
            # 与 YAML 无关的种子条目：正常注入
            coll.insert_one(
                {
                    "_id": seed_spec["slug"],
                    "builtin": True,
                    "seed_hash": agent_spec_hash(seed_spec),
                    "deleted": False,
                    "spec": seed_spec,
                    "created_at": now,
                    "updated_at": now,
                }
            )
            stats["inserted_builtin"] += 1
            continue
        yaml_matched = True
        same = yaml_hash == agent_spec_hash(seed_spec)
        coll.insert_one(
            {
                "_id": seed_spec["slug"],
                "builtin": same,
                "seed_hash": agent_spec_hash(seed_spec),
                "deleted": False,
                "spec": seed_spec if same else yaml_spec,
                "created_at": now,
                "updated_at": now,
            }
        )
        stats["inserted_builtin" if same else "migrated_user_modified"] += 1

    # YAML 独有工作流（用户自建，种子没有）→ builtin=false
    if not yaml_matched:
        coll.insert_one(
            {
                "_id": yaml_spec["slug"],
                "builtin": False,
                "seed_hash": None,
                "deleted": False,
                "spec": yaml_spec,
                "created_at": now,
                "updated_at": now,
            }
        )
        stats["migrated_user_modified"] += 1

    store.invalidate_store_cache()
    logger.info("🌱 [seeder] 首次迁移完成（default.yaml → workflow_specs）: %s", stats)
    return stats


def sync_workflow_specs() -> Dict[str, int]:
    migrated = _first_time_migrate_workflows()
    if migrated is not None:
        return migrated

    stats = {"inserted": 0, "upgraded": 0, "kept": 0, "tombstoned": 0}
    for seed_spec in load_workflow_seeds():
        action = store.upsert_workflow_spec_from_seed(seed_spec)
        stats[action] = stats.get(action, 0) + 1
    return stats


def sync_all() -> Dict[str, Dict[str, int]]:
    """全量同步（lifespan / worker main 挂载点）。"""
    agent_stats = sync_agent_specs()
    workflow_stats = sync_workflow_specs()
    logger.info(
        "🌱 [seeder] 种子同步完成: agents=%s, workflows=%s",
        agent_stats,
        workflow_stats,
    )
    return {"agents": agent_stats, "workflows": workflow_stats}
