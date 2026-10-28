"""知识库向量模型配置与文本编码（OpenAI 兼容 /v1/embeddings 通用协议）。

向量模型只走云端 API：base_url + api_key + model_name（+ 可选 dimension），
由用户在 Web UI「设置 → LLM」配置 model_type=embedding 的条目，
解析优先级复用 app/llm/providers.py（模型配置 > 厂家配置）。
"""

import logging
import threading
import time
from typing import List, Optional, Sequence

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 60
_cache_lock = threading.Lock()
_cached_at: float = 0.0
_cached_model: Optional[str] = None
_cached_payload = None  # (provider, api_key, base_url, dimension)


class KBEmbeddingNotConfigured(RuntimeError):
    """未配置可用的向量模型（model_type=embedding）"""


def get_embedding_config(force_refresh: bool = False) -> Optional[dict]:
    """当前生效的向量模型配置（带 60s 进程内缓存，仅缓存命中结果）。

    返回 {"provider", "model_name", "api_key", "base_url", "dimension"}；
    未配置返回 None。
    """
    global _cached_at, _cached_model, _cached_payload

    if not force_refresh:
        with _cache_lock:
            if (
                _cached_payload is not None
                and time.time() - _cached_at < _CACHE_TTL_SECONDS
            ):
                return _as_dict(_cached_model, _cached_payload)

    from app.llm.providers import resolve_embedding_config

    resolved = resolve_embedding_config()
    if resolved is None:
        return None
    with _cache_lock:
        _cached_model = resolved.model_name
        _cached_payload = (
            resolved.provider,
            resolved.api_key,
            resolved.base_url,
            resolved.dimension,
        )
        _cached_at = time.time()
    return _as_dict(_cached_model, _cached_payload)


def _as_dict(model: Optional[str], payload) -> Optional[dict]:
    provider, api_key, base_url, dimension = payload
    return {
        "provider": provider,
        "model_name": model,
        "api_key": api_key,
        "base_url": base_url,
        "dimension": dimension,
    }


def get_embedding_status() -> dict:
    """向量模型配置状态（知识库页索引状态 tab 用；api_key 脱敏）。"""
    cfg = get_embedding_config()
    if cfg is None:
        return {"configured": False}
    return {
        "configured": True,
        "provider": cfg["provider"],
        "model_name": cfg["model_name"],
        "base_url": cfg["base_url"] or "https://api.openai.com/v1（默认）",
        "dimension": cfg["dimension"],
    }


def embed_texts(texts: Sequence[str]) -> List[List[float]]:
    """批量编码文本（阻塞 HTTP，调用方负责放线程池）。

    未配置向量模型或缺少 api_key 抛 KBEmbeddingNotConfigured。
    """
    cfg = get_embedding_config()
    if cfg is None:
        raise KBEmbeddingNotConfigured("未配置 model_type=embedding 的向量模型")
    if not cfg["api_key"]:
        raise KBEmbeddingNotConfigured(f"向量模型 {cfg['model_name']} 缺少 API Key")

    from openai import OpenAI

    from app.core.config import settings

    client = OpenAI(
        api_key=cfg["api_key"],
        base_url=cfg["base_url"] or None,
        timeout=120.0,
    )
    batch_size = settings.KB_EMBEDDING_BATCH_SIZE
    embeddings: List[List[float]] = []
    for i in range(0, len(texts), batch_size):
        chunk = [t if t and t.strip() else " " for t in texts[i:i + batch_size]]
        kwargs = {"model": cfg["model_name"], "input": chunk}
        if cfg["dimension"]:
            kwargs["dimensions"] = cfg["dimension"]
        resp = client.embeddings.create(**kwargs)
        embeddings.extend(item.embedding for item in resp.data)
    return embeddings
