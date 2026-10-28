"""知识库 ChromaDB 向量存储（持久化，市场独立集合）。

与记忆集合（agents/utils/memory.py，进程内临时的自身经验）分开：
知识库是全市场公共事实语料，必须跨进程重启存活，走 PersistentClient
落在 runtime/data/kb_chroma/。单进程内串行访问（后端进程持有唯一客户端）。
"""

import logging
import threading
from typing import Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

_client = None
_client_lock = threading.Lock()
_collections: Dict[str, object] = {}


def _get_client():
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                import chromadb
                from chromadb.config import Settings as ChromaSettings

                from app.core.config import settings

                path = settings.resolve_runtime_path(settings.KB_CHROMA_DIR)
                _client = chromadb.PersistentClient(
                    path=path,
                    settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True),
                )
                logger.info(f"[kb] ChromaDB 持久化客户端就绪: {path}")
    return _client


def collection_name(market: str) -> str:
    return f"kb_news_{market.lower()}"


def _get_collection(market: str):
    name = collection_name(market)
    if name in _collections:
        return _collections[name]
    # 余弦相似（默认 l2 对文本相似不友好）；集合自描述维度信息
    col = _get_client().get_or_create_collection(
        name=name, metadata={"hnsw:space": "cosine"}
    )
    _collections[name] = col
    return col


def _drop_cached(market: str):
    _collections.pop(collection_name(market), None)


def upsert_documents(
    market: str,
    ids: Sequence[str],
    documents: Sequence[str],
    embeddings: Sequence[Sequence[float]],
    metadatas: Sequence[Dict],
) -> int:
    col = _get_collection(market)
    col.upsert(
        ids=list(ids),
        documents=list(documents),
        embeddings=[list(e) for e in embeddings],
        metadatas=list(metadatas),
    )
    return len(ids)


def query(
    market: str,
    query_embedding: Sequence[float],
    n_results: int = 6,
    where: Optional[Dict] = None,
) -> List[Dict]:
    """相似检索；维度不匹配（模型已切换未重建）抛异常由调用方降级。"""
    col = _get_collection(market)
    kwargs = {
        "query_embeddings": [list(query_embedding)],
        "n_results": n_results,
        "include": ["documents", "metadatas", "distances"],
    }
    if where:
        kwargs["where"] = where
    result = col.query(**kwargs)
    docs = (result.get("documents") or [[]])[0]
    metas = (result.get("metadatas") or [[]])[0]
    dists = (result.get("distances") or [[]])[0]
    items = []
    for doc, meta, dist in zip(docs, metas, dists):
        meta = meta or {}
        meta["snippet"] = (doc or "")[:200]
        meta["distance"] = dist
        meta["similarity"] = 1.0 - dist
        items.append(meta)
    return items


def collection_count(market: str) -> int:
    try:
        return _get_collection(market).count()
    except Exception as e:  # noqa: BLE001 - 集合不存在等视为空
        logger.debug(f"[kb] 读取集合 {collection_name(market)} 数量失败: {e}")
        return 0


def delete_collection(market: str) -> bool:
    """重建入口：删除集合并清缓存。"""
    _drop_cached(market)
    try:
        _get_client().delete_collection(name=collection_name(market))
        logger.info(f"[kb] 已删除集合 {collection_name(market)}（待全量重建）")
        return True
    except Exception as e:  # noqa: BLE001 - 集合本就不存在
        logger.debug(f"[kb] 删除集合 {collection_name(market)} 失败（可能不存在）: {e}")
        return False
