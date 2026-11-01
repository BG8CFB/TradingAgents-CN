"""知识库增量索引器（独立 cron，与结算链路解耦）。

增量语义：按 news 集合 updated_at checkpoint 扫描新入库/更新的语料，
整篇一向量（不分块）写入 kb_news_{market}。向量模型或维度变更时自动全量重建
（旧向量空间与新模型不兼容）。索引状态持久在 kb_index_state 集合。
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.data.knowledge import vector_store
from app.data.knowledge.config import embed_texts, get_embedding_config
from app.data.knowledge.util import parse_publish_ts
from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name

logger = logging.getLogger(__name__)

MARKETS = ("CN", "HK", "US")

# 单轮增量扫描的软上限（防止首轮全量把进程拖死；全量重建分轮推进）
_SCAN_BATCH = 200


async def load_all_states() -> Dict[str, Dict]:
    """读取全部市场索引状态 {market: state}。"""
    return {m: await _load_state(m) for m in MARKETS}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _load_state(market: str) -> Dict:
    db = get_motor_db()
    coll = db[get_collection_name("kb_index_state", market)]
    doc = await coll.find_one({"market": market})
    return doc or {"market": market}


async def load_state(market: str) -> Dict:
    """读取市场索引状态（知识库页/路由概览用，公开只读入口）。"""
    state = await _load_state(market)
    state.setdefault("indexed_count", 0)
    return state


async def _save_state(market: str, updates: Dict) -> None:
    db = get_motor_db()
    coll = db[get_collection_name("kb_index_state", market)]
    updates["market"] = market
    updates["updated_at"] = _now_iso()
    await coll.update_one(
        {"market": market}, {"$set": updates, "$setOnInsert": {"created_at": _now_iso()}},
        upsert=True,
    )


def _doc_text(doc: Dict, max_chars: int) -> str:
    title = doc.get("title") or ""
    body = doc.get("content") or ""
    if not body:
        summary = doc.get("summary") or ""
        # 语料 summary 常是标题复写，与标题相同时只保留标题一遍
        body = summary if summary and summary != title else ""
    text = f"{title}\n{body}".strip()
    return text[:max_chars] if len(text) > max_chars else text


def _normalize_publish_time(value) -> str:
    """publish_time 统一成字符串（CN 档可能是 datetime），dedup/元数据共用。"""
    if hasattr(value, "isoformat"):
        return value.isoformat(sep=" ")
    return str(value) if value else ""


def _dedup_key(doc: Dict) -> tuple:
    # content_hash 并入 symbol 前的历史档与重刷档会同文并存，索引侧按内容键去重
    return (doc.get("symbol") or "", doc.get("title") or "", doc.get("publish_time") or "")


async def _index_batch(market: str, docs: List[Dict], embedding_cfg: Dict) -> int:
    from app.core.config import settings

    texts, ids, metadatas = [], [], []
    seen = set()
    for doc in docs:
        # dedup 键用归一化后的 publish_time：同一公告 news/announcement 双档
        # 或 datetime/字符串混存时 (title, 时间) 才能真正对上
        key = (
            doc.get("symbol") or "",
            doc.get("title") or "",
            _normalize_publish_time(doc.get("publish_time")),
        )
        if not doc.get("title") or key in seen:
            continue
        seen.add(key)
        # CN 语料 publish_time 可能是 datetime 对象（HK/US 为字符串）；
        # ChromaDB 元数据只收 str/int/float/bool/list，须先扁平化。
        publish_time = _normalize_publish_time(doc.get("publish_time"))
        symbol_raw = doc.get("symbol")
        if symbol_raw is None or (isinstance(symbol_raw, float) and symbol_raw != symbol_raw):
            symbol = ""
        else:
            symbol = str(symbol_raw)
        publish_ts = parse_publish_ts(publish_time) or 0.0
        text = _doc_text(doc, settings.KB_EMBEDDING_MAX_CHARS)
        texts.append(text)
        ids.append(f"{symbol}:{doc.get('content_hash') or key}")
        metadatas.append({
            "symbol": symbol,
            "title": doc.get("title") or "",
            "publish_ts": publish_ts,
            "publish_time": publish_time,
            "data_source": doc.get("data_source") or "",
            "type": doc.get("type") or "news",
            "url": doc.get("url") or "",
            "embedding_model": embedding_cfg["model_name"],
            "dimension": embedding_cfg["dimension"] or 0,  # 实际维度写入时回填
        })
    if not texts:
        return 0

    embeddings = await asyncio.to_thread(embed_texts, texts)
    actual_dim = len(embeddings[0])
    for meta in metadatas:
        if not meta["dimension"]:
            meta["dimension"] = actual_dim

    vector_store.upsert_documents(market, ids, texts, embeddings, metadatas)
    return len(texts)


async def _scan_and_index(market: str, since: Optional[str], embedding_cfg: Dict) -> Dict:
    """从 checkpoint 扫描并索引，返回本轮统计（updated_at 游标随之推进）。"""
    from app.data.storage.mongo.repositories.news_repo import NewsRepo

    repo = NewsRepo()
    cursor = since
    total = 0
    while True:
        docs = await repo.get_updated_since(market, cursor, limit=_SCAN_BATCH)
        if not docs:
            break
        total += await _index_batch(market, docs, embedding_cfg)
        cursor = docs[-1].get("updated_at") or cursor
        if len(docs) < _SCAN_BATCH:
            break
    return {"indexed": total, "checkpoint": cursor}


async def run_incremental(market: Optional[str] = None) -> Dict:
    """增量索引入口（cron / 手动触发）。market 为空跑全部市场。"""
    targets = [market] if market else list(MARKETS)
    summary = {}
    for m in targets:
        summary[m] = await _run_market_incremental(m)
    return summary


async def _run_market_incremental(market: str) -> Dict:
    cfg = get_embedding_config()
    state = await _load_state(market)
    if cfg is None:
        await _save_state(market, {"status": "skipped", "last_error": "未配置向量模型"})
        return {"status": "skipped", "reason": "未配置向量模型"}

    try:
        # 向量模型/维度变更 → 旧索引不兼容，自动全量重建
        state_dim = state.get("dimension")
        model_changed = state.get("embedding_model") != cfg["model_name"]
        dim_changed = cfg["dimension"] is not None and state_dim != cfg["dimension"]
        # 物理自愈：状态称已索引但集合实际为空（进程崩溃/并发写损坏等），
        # checkpoint 已推进的增量永远扫不回旧数据，必须全量重建
        physical_empty = bool(state.get("indexed_count")) and vector_store.collection_count(market) == 0
        if physical_empty:
            logger.warning(
                f"[kb] {market} 索引状态与物理集合不符"
                f"（state={state.get('indexed_count')} 实际=0），自动全量重建自愈"
            )
            return await rebuild_market(market)
        if model_changed or dim_changed:
            logger.info(
                f"[kb] {market} 向量模型签名变更 "
                f"({state.get('embedding_model')}/{state_dim}→"
                f"{cfg['model_name']}/{cfg['dimension']})，触发全量重建"
            )
            return await rebuild_market(market)

        await _save_state(market, {"status": "indexing", "last_error": None})
        result = await _scan_and_index(market, state.get("checkpoint"), cfg)
        count = vector_store.collection_count(market)
        actual_dim = cfg["dimension"] or state_dim or await _read_actual_dimension(market)
        await _save_state(market, {
            "status": "ready",
            "checkpoint": result["checkpoint"],
            "indexed_count": count,
            "embedding_model": cfg["model_name"],
            "embedding_provider": cfg["provider"],
            "dimension": actual_dim,
            "last_run": _now_iso(),
        })
        return {"status": "ready", "indexed_this_run": result["indexed"], "indexed_count": count}
    except Exception as e:  # noqa: BLE001 - 索引失败记状态，不抛给 cron
        logger.error(f"[kb] {market} 增量索引失败: {e}", exc_info=True)
        await _save_state(market, {"status": "error", "last_error": str(e)[:500]})
        return {"status": "error", "error": str(e)}


async def rebuild_market(market: str) -> Dict:
    """全量重建：清空集合与 checkpoint 后重新扫描（分轮推进，不阻塞其它市场）。"""
    cfg = get_embedding_config()
    if cfg is None:
        return {"status": "skipped", "reason": "未配置向量模型"}

    vector_store.delete_collection(market)
    await _save_state(market, {
        "status": "rebuilding",
        "checkpoint": None,
        "indexed_count": 0,
        "embedding_model": cfg["model_name"],
        "embedding_provider": cfg["provider"],
        "dimension": cfg["dimension"],
        "last_error": None,
    })
    try:
        result = await _scan_and_index(market, None, cfg)
        count = vector_store.collection_count(market)
        state_update: Dict = {
            "status": "ready",
            "checkpoint": result["checkpoint"],
            "indexed_count": count,
            "last_run": _now_iso(),
        }
        if count and not cfg["dimension"]:
            # dimension 留空 = 模型默认：用实际向量维度回填签名
            dim = await _read_actual_dimension(market)
            if dim:
                state_update["dimension"] = dim
        await _save_state(market, state_update)
        logger.info(f"[kb] {market} 全量重建完成: {count} 条")
        return {"status": "ready", "indexed_count": count}
    except Exception as e:  # noqa: BLE001
        logger.error(f"[kb] {market} 全量重建失败: {e}", exc_info=True)
        await _save_state(market, {"status": "error", "last_error": str(e)[:500]})
        return {"status": "error", "error": str(e)}


async def _read_actual_dimension(market: str) -> Optional[int]:
    col = vector_store._get_collection(market)
    if col.count() == 0:
        return None
    got = col.get(limit=1, include=["metadatas"])
    metas = (got or {}).get("metadatas") or []
    if metas and isinstance(metas[0], dict):
        dim = metas[0].get("dimension")
        if isinstance(dim, int) and dim > 0:
            return dim
    return None
