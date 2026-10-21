"""保主源写入（PRD FR-07 规则 3：双源交叉校验，不一致时保留既有源值）。

背景：业务域唯一键**不含 `data_source`**（单版本覆盖），谁后写谁生效。QMT 定位
为兜底源（D-2），但它的盘后采集时间天然晚于既有源 → 若直接 upsert，就会把
tushare 已入库的正确值覆盖成 qmt 值。FR-07 明确要求反过来：
「与 tushare 双源交叉校验，不一致率 > 0.5% 时告警并**保留 tushare 值**」。

本模块实现「写前对账 + 选择性写入」：
1. 批量取既有文档（`$or` 分块，避免 N 次单条查询）；
2. 逐条判定：
   - 无既有文档           → 写入（补缺，这是兜底源的正当职责）
   - 既有文档来源 = 自己   → 写入（更新自己上次写的值）
   - 既有文档来源 ≠ 自己   → **比对**：一致则跳过（省一次写），不一致则**跳过并计数**
3. 不一致率超阈值 → 写 `sync_events` 告警（`data_source="qmt_cross_check"`）。

注意这是**域级策略**，不是全局默认：日线/分时/tick 是否也改为「只补缺口」属
P1-7 待拍板项，本模块先服务 FR-07 明确要求的复权因子域。
"""

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.config import settings

logger = logging.getLogger("worker.qmt")

# 浮点比较相对容差：分红的派息额/因子本身是低精度数值
_REL_TOL = 1e-6
# `$or` 过滤块大小：Mongo 对单次查询的 $or 分支数量有限制，200 稳妥
_OR_CHUNK = 200


def _values_differ(old: Dict, new: Dict, fields: Sequence[str]) -> bool:
    """逐字段比较（数值用相对容差，缺失与非数值用等值）。"""
    for f in fields:
        a, b = old.get(f), new.get(f)
        if a is None and b is None:
            continue
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            if abs(float(a) - float(b)) > _REL_TOL * max(
                1.0, abs(float(a)), abs(float(b))
            ):
                return True
        elif a != b:
            return True
    return False


async def _load_existing(
    domain: str, market: str, filters: List[Dict],
    key_fields: List[str], compare_fields: Sequence[str],
) -> Dict[Tuple, Dict]:
    """批量读取既有记录，返回 {唯一键元组: 文档}。"""
    from app.data.storage.mongo.client import get_motor_db
    from app.data.storage.mongo.collections import get_collection_name

    projection = {"_id": 0, "data_source": 1}
    for f in [*key_fields, *compare_fields]:
        projection[f] = 1

    coll = get_motor_db()[get_collection_name(domain, market)]
    out: Dict[Tuple, Dict] = {}
    for i in range(0, len(filters), _OR_CHUNK):
        chunk = filters[i: i + _OR_CHUNK]
        cursor = coll.find({"$or": chunk}, projection)
        for doc in await cursor.to_list(length=None):
            out[tuple(doc.get(f) for f in key_fields)] = doc
    return out


async def _alert_mismatch(
    domain: str, market: str, rate: float, mismatched: int,
    compared: int, threshold: float, samples: List[Dict],
) -> None:
    """不一致率超阈值 → 写告警事件（PRD FR-07 规则 3 / 附录 B 埋点）。"""
    try:
        from app.data.storage.mongo.client import get_motor_db
        from app.data.storage.mongo.collections import get_collection_name
        from app.utils.timezone import now_utc

        db = get_motor_db()
        await db[get_collection_name("sync_events", market)].insert_one({
            "event_type": "SYNC_FAILED",
            "domain": domain,
            "source": "qmt",
            "market": market,
            "symbol": None,
            "record_count": mismatched,
            "duration_ms": 0,
            "error_message": (
                f"双源不一致率 {rate:.2%} > 阈值 {threshold:.2%}"
                f"（{mismatched}/{compared}），已保留既有源值"
            ),
            "data_source": "qmt_cross_check",
            "mismatch_rate": round(rate, 6),
            "mismatch_count": mismatched,
            "compared_count": compared,
            "threshold": threshold,
            "samples": samples[:10],
            "updated_at": now_utc().isoformat(),
        })
    except Exception as e:  # noqa: BLE001 — 告警写失败不影响采集
        logger.debug("双源交叉校验告警写入失败（忽略）: %s", e)


async def write_preserving_primary(
    domain: str,
    records: List[Dict],
    market: str,
    *,
    compare_fields: Sequence[str],
    source: str = "qmt",
    mismatch_threshold: Optional[float] = None,
) -> Dict[str, Any]:
    """只补缺口与自我更新，不覆盖其他源的值；返回写入/对账统计。

    Args:
        domain: 业务域（用于取唯一键与集合名）。
        records: Router 产出的 db-ready dicts。
        market: 市场。
        compare_fields: 交叉校验的字段（如 ``["adj_factor"]``）。
        source: 本写入方标识（默认 qmt）。
        mismatch_threshold: 不一致率告警阈值；None → settings。

    Returns:
        ``{"written", "kept_existing", "skipped_same", "compared",
        "mismatched", "mismatch_rate", "alerted"}``
    """
    from app.data.storage.mongo.repositories.key_spec import build_filter, get_domain_key
    from app.worker.base_market_sync import _get_repo

    result: Dict[str, Any] = {
        "written": 0, "kept_existing": 0, "skipped_same": 0,
        "compared": 0, "mismatched": 0, "mismatch_rate": 0.0, "alerted": False,
    }
    if not records:
        return result

    threshold = float(
        mismatch_threshold if mismatch_threshold is not None
        else settings.QMT_CROSS_CHECK_THRESHOLD
    )
    key_fields = get_domain_key(domain)

    filters: List[Dict] = []
    valid: List[Dict] = []
    for rec in records:
        try:
            filters.append(build_filter(domain, rec))
            valid.append(rec)
        except KeyError:
            continue  # 缺唯一键字段 → 交给 Repo 层跳过

    existing = await _load_existing(
        domain, market, filters, key_fields, compare_fields
    )

    to_write: List[Dict] = []
    samples: List[Dict] = []
    for rec in valid:
        key = tuple(rec.get(f) for f in key_fields)
        old = existing.get(key)
        if old is None or old.get("data_source") == source:
            to_write.append(rec)
            continue
        result["compared"] += 1
        if _values_differ(old, rec, compare_fields):
            # 不一致 → 保留既有主源值（PRD FR-07 规则 3），不写不删
            result["kept_existing"] += 1
            if len(samples) < 10:
                samples.append({
                    "key": {f: rec.get(f) for f in key_fields},
                    "existing": {f: old.get(f) for f in compare_fields},
                    "incoming": {f: rec.get(f) for f in compare_fields},
                    "existing_source": old.get("data_source"),
                })
        else:
            result["skipped_same"] += 1

    if to_write:
        result["written"] = await _get_repo(domain).upsert_many(to_write, market)

    compared = result["compared"]
    if compared:
        rate = result["kept_existing"] / compared
        result["mismatched"] = result["kept_existing"]
        result["mismatch_rate"] = round(rate, 6)
        if rate > threshold:
            result["alerted"] = True
            await _alert_mismatch(
                domain, market, rate, result["kept_existing"], compared,
                threshold, samples,
            )
            logger.warning(
                "双源交叉校验 %s 不一致率 %.2f%% > %.2f%%（%d/%d），已保留既有源值",
                domain, rate * 100, threshold * 100,
                result["kept_existing"], compared,
            )
    return result
