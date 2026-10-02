# data-access-exempt: 工作流 spec 专用存储层（自身即数据访问模块，同类先例 skill/state_store.py）
"""智能体库与工作流的 DB 存取层（Mongo agent_specs / workflow_specs 集合）。

权威与降级：
- DB 是运行时唯一权威（seeder 启动时注入种子，用户编辑写回 DB）
- 本地种子 JSON 仅在 DB 不可达或集合尚未注入时作只读降级（WARNING，不阻断）

文档形状（agent_specs）：
    _id=slug, phase(1|2|3), position(int, phase 内展示序), builtin(bool),
    seed_hash(种子内容 hash，升级判据), deleted(bool, tombstone), spec({...原条目}),
    created_at, updated_at
workflow_specs 同形（无 phase/position，_id=workflow slug，spec=WorkflowSpec dump）。

tombstone 语义：内置条目被用户删除后 deleted=true，seeder 升级种子时不复活；
非种子条目被删除则物理删除。builtin=false 表示用户修改过（seeder 不覆盖）。
"""

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pymongo import UpdateOne
from pymongo.errors import PyMongoError

from app.engine.orchestrator.workflow import seeds as seeds_mod
from app.engine.orchestrator.workflow.seeds import agent_spec_hash

logger = logging.getLogger(__name__)

AGENT_SPECS_COLLECTION = "agent_specs"
WORKFLOW_SPECS_COLLECTION = "workflow_specs"

# 读缓存 TTL：跨进程（API 保存 vs worker 读取）最终一致窗口。
# worker 任务边界会显式 invalidate（见 DynamicAnalystFactory.clear_cache 联动）。
CACHE_TTL_SECONDS = 30.0
# 降级 WARNING 频控（同一进程 60s 内最多一条，避免刷屏）
_WARN_INTERVAL_SECONDS = 60.0

_lock = threading.Lock()
_cache: Dict[str, tuple] = {}
_last_fallback_warn = 0.0


def _db():
    from app.core.database import get_mongo_db_sync

    return get_mongo_db_sync()


def _cache_get(key: str) -> Optional[Any]:
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
    return None


def _cache_set(key: str, value: Any) -> None:
    with _lock:
        _cache[key] = (time.monotonic() + CACHE_TTL_SECONDS, value)


def invalidate_store_cache() -> None:
    """清空本进程读缓存（写路径后、worker 任务边界调用）。"""
    with _lock:
        _cache.clear()


def _warn_fallback(reason: str) -> None:
    global _last_fallback_warn
    now = time.monotonic()
    if now - _last_fallback_warn < _WARN_INTERVAL_SECONDS:
        return
    _last_fallback_warn = now
    logger.warning("⚠️ [workflow-store] %s，降级读取本地种子（只读）", reason)


# ---------------------------------------------------------------------------
# agent_specs：读取
# ---------------------------------------------------------------------------


def _seed_agent_docs(phase: Optional[int] = None) -> List[Dict[str, Any]]:
    """从本地种子组装只读文档视图（降级路径；deleted 恒 false）。"""
    docs = []
    position_by_phase: Dict[int, int] = {}
    for entry in seeds_mod.load_agent_seeds():
        ph = entry["phase"]
        if phase is not None and ph != phase:
            continue
        pos = position_by_phase.get(ph, 0)
        position_by_phase[ph] = pos + 1
        docs.append(
            {
                "_id": entry["spec"]["slug"],
                "phase": ph,
                "position": pos,
                "builtin": True,
                "seed_hash": agent_spec_hash(entry["spec"]),
                "deleted": False,
                "spec": entry["spec"],
            }
        )
    return docs


def _list_agent_docs(phase: Optional[int] = None, include_deleted: bool = False) -> List[Dict[str, Any]]:
    """DB 读取（带缓存与种子降级），按 (phase, position) 排序。"""
    cache_key = f"agent_docs:phase={phase}:deleted={include_deleted}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        query: Dict[str, Any] = {}
        if phase is not None:
            query["phase"] = phase
        if not include_deleted:
            query["deleted"] = {"$ne": True}
        docs = list(_db()[AGENT_SPECS_COLLECTION].find(query).sort([("phase", 1), ("position", 1)]))
        if not docs and phase is None:
            # 集合尚未注入（seeder 未跑过）——种子是等价内容，静默降级
            docs = _seed_agent_docs()
        elif not docs and phase is not None:
            # 单 phase 为空有两种可能：已注入但该 phase 被清空（合法，tombstone 后）
            # 或整体未注入（种子降级）。用全集合探测区分。
            if _db()[AGENT_SPECS_COLLECTION].count_documents({}) == 0:
                docs = _seed_agent_docs(phase)
        docs = [d for d in docs if include_deleted or not d.get("deleted")]
        _cache_set(cache_key, docs)
        return docs
    except PyMongoError as e:
        _warn_fallback(f"agent_specs 读取失败: {e}")
        return _seed_agent_docs(phase)


def list_agent_specs(phase: Optional[int] = None) -> List[Dict[str, Any]]:
    """智能体库（消费者视角）：返回 spec dict 列表，不含 tombstone 条目。"""
    return [d["spec"] for d in _list_agent_docs(phase)]


def list_agent_docs(phase: Optional[int] = None) -> List[Dict[str, Any]]:
    """带元数据视图（builtin/position 等），管理面用。"""
    return _list_agent_docs(phase)


def get_agent_spec(slug: str) -> Optional[Dict[str, Any]]:
    """按 slug 精确取一个智能体条目（跨 phase），未找到返回 None。

    已注入的库中条目不存在或处于 tombstone 时返回 None——不回退种子（否则
    会把用户删除的内置条目复活）。
    """
    try:
        coll = _db()[AGENT_SPECS_COLLECTION]
        doc = coll.find_one({"_id": slug, "deleted": {"$ne": True}})
        if doc is not None:
            return doc["spec"]
        if coll.count_documents({}) > 0:
            return None
    except PyMongoError as e:
        _warn_fallback(f"agent_specs 单条读取失败: {e}")
    for doc in _seed_agent_docs():
        if doc["_id"] == slug:
            return doc["spec"]
    return None


# ---------------------------------------------------------------------------
# agent_specs：写入
# ---------------------------------------------------------------------------


def replace_phase_agent_specs(phase: int, entries: List[Dict[str, Any]]) -> None:
    """全量覆盖某 phase（PUT /api/agent-configs/{phase} 语义）。

    - payload 条目：按提交顺序写 position；内容与种子一致的标 builtin=true
    - 不在 payload 的种子条目：写 tombstone（builtin=true + deleted=true，防 seed 复活）
    - 不在 payload 的非种子条目：物理删除
    """
    now = datetime.now(timezone.utc)
    coll = _db()[AGENT_SPECS_COLLECTION]
    seed_by_slug = seeds_mod.agent_seed_by_slug()
    payload_slugs = {e["slug"] for e in entries}

    existing_slugs = {d["_id"] for d in coll.find({"phase": phase}, {"_id": 1})}
    seed_slugs_of_phase = {s for s, e in seed_by_slug.items() if e["phase"] == phase}

    ops: List[Dict[str, Any]] = []
    for pos, entry in enumerate(entries):
        slug = entry["slug"]
        seed_entry = seed_by_slug.get(slug)
        content_hash = agent_spec_hash(entry)
        builtin = bool(
            seed_entry and seed_entry["phase"] == phase and content_hash == agent_spec_hash(seed_entry["spec"])
        )
        ops.append(
            {
                "_id": slug,
                "phase": phase,
                "position": pos,
                "builtin": builtin,
                "seed_hash": agent_spec_hash(seed_entry["spec"]) if builtin else None,
                "deleted": False,
                "spec": entry,
                "updated_at": now,
            }
        )

    try:
        bulk = [UpdateOne({"_id": op["_id"]}, {"$set": op}, upsert=True) for op in ops]
        # 不在 payload 的种子条目 → tombstone（builtin=true + deleted=true，
        # spec 保留种子内容供「恢复默认」；deleted 主导一切读取判断）
        for slug in seed_slugs_of_phase - payload_slugs:
            seed_spec = seed_by_slug[slug]["spec"]
            bulk.append(
                UpdateOne(
                    {"_id": slug},
                    {
                        "$set": {
                            "_id": slug,
                            "phase": phase,
                            "position": len(entries),
                            "builtin": True,
                            "seed_hash": agent_spec_hash(seed_spec),
                            "deleted": True,
                            "spec": seed_spec,
                            "updated_at": now,
                        }
                    },
                    upsert=True,
                )
            )
        if bulk:
            coll.bulk_write(bulk, ordered=False)
        # 不在 payload 的非种子条目 → 物理删除
        doomed = existing_slugs - payload_slugs - seed_slugs_of_phase
        if doomed:
            coll.delete_many({"_id": {"$in": sorted(doomed)}})
    finally:
        invalidate_store_cache()


def get_agent_doc(slug: str) -> Optional[Dict[str, Any]]:
    """按 slug 取智能体文档（含 phase/builtin/deleted 元数据，管理面判定用）。"""
    try:
        return _db()[AGENT_SPECS_COLLECTION].find_one({"_id": slug})
    except PyMongoError as e:
        _warn_fallback(f"agent_specs 文档读取失败: {e}")
        return None


def save_agent_spec(spec: Dict[str, Any], phase: int, position: Optional[int] = None) -> None:
    """新建/更新单个智能体条目（/api/agents 单条 CRUD 的写路径）。

    builtin 恒 false（用户条目；种子条目由 seeder 与 replace_phase 管理）。
    position 缺省 = 该 phase 现有最大值 +1（新建追加到末尾）。同名 tombstone
    被覆盖复活（用户显式重建，非 seed 复活路径）。
    """
    now = datetime.now(timezone.utc)
    coll = _db()[AGENT_SPECS_COLLECTION]
    slug = spec["slug"]
    if position is None:
        last = coll.find_one({"phase": phase}, sort=[("position", -1)], projection={"position": 1})
        position = (last or {}).get("position", -1) + 1
    coll.update_one(
        {"_id": slug},
        {
            "$set": {
                "_id": slug,
                "phase": phase,
                "position": position,
                "builtin": False,
                "seed_hash": None,
                "deleted": False,
                "spec": spec,
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    invalidate_store_cache()


def delete_agent_spec(slug: str) -> str:
    """删除单个智能体条目，返回动作：tombstoned / deleted / missing。

    种子条目（slug 命中本地种子）→ tombstone（deleted=true，防 seed 复活，
    内容保留供「恢复默认」）；用户条目 → 物理删除。builtin 403 判定在调用方。
    """
    coll = _db()[AGENT_SPECS_COLLECTION]
    doc = coll.find_one({"_id": slug}, projection={"_id": 1})
    if doc is None:
        return "missing"
    if slug in seeds_mod.agent_seed_by_slug():
        coll.update_one(
            {"_id": slug},
            {"$set": {"deleted": True, "updated_at": datetime.now(timezone.utc)}},
        )
        invalidate_store_cache()
        return "tombstoned"
    coll.delete_one({"_id": slug})
    invalidate_store_cache()
    return "deleted"


def agent_workflow_references(slug: str) -> List[str]:
    """引用某智能体的工作流 slug 列表（workflow spec 的 nodes 段命中）。

    phase1 pool 动态分析师不进 nodes 段（selected_nodes 运行时勾选），
    不计为结构性引用——删除 phase1 条目只影响默认勾选，不断工作流。
    """
    out: List[str] = []
    try:
        for doc in _list_workflow_docs():
            spec = doc.get("spec") or {}
            nodes = spec.get("nodes") or ()
            if any((n or {}).get("slug") == slug for n in nodes):
                out.append(doc["_id"])
    except PyMongoError as e:
        _warn_fallback(f"工作流引用计数失败: {e}")
    return out


def upsert_agent_spec_from_seed(seed_entry: Dict[str, Any], position: int) -> str:
    """seeder 注入单个种子条目，返回动作：inserted / upgraded / kept / tombstoned。

    - DB 无此条目 → inserted（builtin=true，position 按种子序）
    - deleted=true → tombstoned（不复活，种子内容随文档更新）
    - builtin 且 hash 落后 → upgraded（覆盖为最新种子内容）
    - builtin=false → kept（用户版本不动）
    """
    now = datetime.now(timezone.utc)
    coll = _db()[AGENT_SPECS_COLLECTION]
    slug = seed_entry["spec"]["slug"]
    new_hash = agent_spec_hash(seed_entry["spec"])

    doc = coll.find_one({"_id": slug})
    if doc is None:
        coll.insert_one(
            {
                "_id": slug,
                "phase": seed_entry["phase"],
                "position": position,
                "builtin": True,
                "seed_hash": new_hash,
                "deleted": False,
                "spec": seed_entry["spec"],
                "created_at": now,
                "updated_at": now,
            }
        )
        invalidate_store_cache()
        return "inserted"
    if doc.get("deleted"):
        # tombstone：仅同步最新种子内容与 hash，保持 deleted
        coll.update_one(
            {"_id": slug},
            {"$set": {"seed_hash": new_hash, "spec": seed_entry["spec"], "updated_at": now}},
        )
        invalidate_store_cache()
        return "tombstoned"
    if doc.get("builtin"):
        if doc.get("seed_hash") == new_hash:
            return "kept"
        coll.update_one(
            {"_id": slug},
            {"$set": {"seed_hash": new_hash, "spec": seed_entry["spec"], "updated_at": now}},
        )
        invalidate_store_cache()
        return "upgraded"
    return "kept"  # 用户修改过的条目（builtin=false），种子不覆盖


# ---------------------------------------------------------------------------
# workflow_specs
# ---------------------------------------------------------------------------


def _seed_workflow_docs() -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    return [
        {
            "_id": entry["slug"],
            "builtin": True,
            "seed_hash": agent_spec_hash(entry),
            "deleted": False,
            "spec": entry,
            "created_at": now,
            "updated_at": now,
        }
        for entry in seeds_mod.load_workflow_seeds()
    ]


def _list_workflow_docs(include_deleted: bool = False) -> List[Dict[str, Any]]:
    cache_key = f"workflow_docs:deleted={include_deleted}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        query = {} if include_deleted else {"deleted": {"$ne": True}}
        docs = list(_db()[WORKFLOW_SPECS_COLLECTION].find(query))
        if not docs and not include_deleted and _db()[WORKFLOW_SPECS_COLLECTION].count_documents({}) == 0:
            docs = _seed_workflow_docs()
        _cache_set(cache_key, docs)
        return docs
    except PyMongoError as e:
        _warn_fallback(f"workflow_specs 读取失败: {e}")
        return _seed_workflow_docs()


def list_workflow_specs() -> List[Dict[str, Any]]:
    """工作流库：返回 WorkflowSpec dump 列表。"""
    return [d["spec"] for d in _list_workflow_docs()]


def list_workflow_docs(include_deleted: bool = False) -> List[Dict[str, Any]]:
    """带元数据视图（builtin/updated_at 等），管理面用。"""
    return _list_workflow_docs(include_deleted)


def get_workflow_spec(slug: str) -> Optional[Dict[str, Any]]:
    """按 slug 取工作流，未找到返回 None。"""
    try:
        doc = _db()[WORKFLOW_SPECS_COLLECTION].find_one({"_id": slug, "deleted": {"$ne": True}})
        if doc is not None:
            return doc["spec"]
        if _db()[WORKFLOW_SPECS_COLLECTION].count_documents({}) > 0:
            return None  # 已注入但确实没有此工作流
    except PyMongoError as e:
        _warn_fallback(f"workflow_specs 单条读取失败: {e}")
    for doc in _seed_workflow_docs():
        if doc["_id"] == slug:
            return doc["spec"]
    return None


def get_workflow_doc(slug: str) -> Optional[Dict[str, Any]]:
    """按 slug 取工作流文档（含 builtin/deleted 元数据，管理面判定用）。

    与 get_workflow_spec 不同：tombstone 文档也返回（供「删除后重建」判定），
    未注入/DB 异常时返回 None。
    """
    try:
        return _db()[WORKFLOW_SPECS_COLLECTION].find_one({"_id": slug})
    except PyMongoError as e:
        _warn_fallback(f"workflow_specs 文档读取失败: {e}")
        return None


def save_workflow_spec(spec: Dict[str, Any]) -> None:
    """新建/更新用户自定义工作流（builtin 恒 false；内置条目由 seeder 管理）。

    同名 tombstone 文档被覆盖复活（用户显式重建，非 seed 复活路径）。
    """
    now = datetime.now(timezone.utc)
    slug = spec["slug"]
    _db()[WORKFLOW_SPECS_COLLECTION].update_one(
        {"_id": slug},
        {
            "$set": {
                "_id": slug,
                "builtin": False,
                "seed_hash": None,
                "deleted": False,
                "spec": spec,
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    invalidate_store_cache()


def delete_workflow_spec(slug: str) -> None:
    """软删除（tombstone）：历史任务的 workflow_snapshot 回放不受影响。"""
    now = datetime.now(timezone.utc)
    _db()[WORKFLOW_SPECS_COLLECTION].update_one({"_id": slug}, {"$set": {"deleted": True, "updated_at": now}})
    invalidate_store_cache()


# ---------------------------------------------------------------------------
# 默认工作流（system_configs 持久化，设计文档 §5.4「设为默认」）
# ---------------------------------------------------------------------------

SYSTEM_CONFIGS_COLLECTION = "system_configs"
DEFAULT_WORKFLOW_SETTING_KEY = "default_workflow_slug"


def _active_system_config() -> Optional[Dict[str, Any]]:
    """活跃系统配置文档（is_active + version 最大；与 SystemService 读取口径一致）。"""
    return _db()[SYSTEM_CONFIGS_COLLECTION].find_one({"is_active": True}, sort=[("version", -1)])


def get_default_workflow_slug() -> Optional[str]:
    """默认工作流 slug；未设置或 DB 不可达返回 None（调用方回落内置默认）。"""
    try:
        doc = _active_system_config() or {}
        return (doc.get("system_settings") or {}).get(DEFAULT_WORKFLOW_SETTING_KEY) or None
    except PyMongoError as e:
        _warn_fallback(f"默认工作流设置读取失败: {e}")
        return None


def set_default_workflow_slug(slug: str) -> None:
    """写入默认工作流（合并进活跃 system_configs 的 system_settings，不动其它键）。

    无活跃系统配置时插入仅承载 system_settings 的最小文档（形状对齐
    SystemService.get_system_config 的容错读取，缺省字段由其 setdefault 补齐）。
    """
    now = datetime.now(timezone.utc)
    coll = _db()[SYSTEM_CONFIGS_COLLECTION]
    doc = _active_system_config()
    if doc is None:
        coll.insert_one(
            {
                "config_name": "workflow-default",
                "config_type": "system",
                "version": 1,
                "is_active": True,
                "llm_configs": [],
                "system_settings": {DEFAULT_WORKFLOW_SETTING_KEY: slug},
                "created_at": now,
                "updated_at": now,
            }
        )
        return
    coll.update_one(
        {"_id": doc["_id"]},
        {"$set": {f"system_settings.{DEFAULT_WORKFLOW_SETTING_KEY}": slug, "updated_at": now}},
    )


def clear_default_workflow_slug() -> None:
    """清除默认工作流设置（回落内置默认；删除当前默认工作流时调用）。"""
    try:
        doc = _active_system_config()
        if doc is not None:
            _db()[SYSTEM_CONFIGS_COLLECTION].update_one(
                {"_id": doc["_id"]},
                {"$unset": {f"system_settings.{DEFAULT_WORKFLOW_SETTING_KEY}": ""}},
            )
    except PyMongoError as e:
        _warn_fallback(f"默认工作流设置清除失败: {e}")


def upsert_workflow_spec_from_seed(seed_spec: Dict[str, Any]) -> str:
    """seeder 注入工作流种子，动作语义同 upsert_agent_spec_from_seed。"""
    now = datetime.now(timezone.utc)
    coll = _db()[WORKFLOW_SPECS_COLLECTION]
    slug = seed_spec["slug"]
    new_hash = agent_spec_hash(seed_spec)

    doc = coll.find_one({"_id": slug})
    if doc is None:
        coll.insert_one(
            {
                "_id": slug,
                "builtin": True,
                "seed_hash": new_hash,
                "deleted": False,
                "spec": seed_spec,
                "created_at": now,
                "updated_at": now,
            }
        )
        invalidate_store_cache()
        return "inserted"
    if doc.get("deleted"):
        coll.update_one(
            {"_id": slug},
            {"$set": {"seed_hash": new_hash, "spec": seed_spec, "updated_at": now}},
        )
        invalidate_store_cache()
        return "tombstoned"
    if doc.get("builtin"):
        if doc.get("seed_hash") == new_hash:
            return "kept"
        coll.update_one(
            {"_id": slug},
            {"$set": {"seed_hash": new_hash, "spec": seed_spec, "updated_at": now}},
        )
        invalidate_store_cache()
        return "upgraded"
    return "kept"


def workflow_collection_initialized() -> bool:
    """DB 中 workflow_specs 是否已注入（区分「未注入」与「被清空」）。"""
    try:
        return _db()[WORKFLOW_SPECS_COLLECTION].count_documents({}) > 0
    except PyMongoError as e:
        _warn_fallback(f"workflow_specs 探测失败: {e}")
        return False


def agent_collection_initialized() -> bool:
    try:
        return _db()[AGENT_SPECS_COLLECTION].count_documents({}) > 0
    except PyMongoError as e:
        _warn_fallback(f"agent_specs 探测失败: {e}")
        return False
