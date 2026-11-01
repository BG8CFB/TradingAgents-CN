"""知识库检索：向量相似 + where 过滤（symbol / publish_ts <= as_of / 类型）。

as_of 防前视是硬约束：分析注入路径必须传 analysis_date，
保证检索结果只含分析日期前发布的语料。本模块为同步实现
（Chroma 与 embedding 均为阻塞调用），调用方放线程池。
"""

import logging
from typing import Dict, List, Optional

from app.data.knowledge import vector_store
from app.data.knowledge.config import embed_texts
from app.data.knowledge.util import end_of_day_ts, normalize_symbol, parse_publish_ts

logger = logging.getLogger(__name__)


def search(
    market: str,
    symbol: str,
    query: str,
    as_of: Optional[str] = None,
    top_k: int = 6,
    types: Optional[List[str]] = None,
    start_date: Optional[str] = None,
) -> List[Dict]:
    """按 symbol + 语义查询检索 top-K 语料。

    Args:
        market: CN / HK / US
        symbol: 股票代码（自动归一）
        query: 检索文本（关键词或自然语言）
        as_of: 截止日期（YYYY-MM-DD 或完整时间串），仅返回不晚于该时间发布的语料
        top_k: 返回条数
        types: 语料类型过滤（news/announcement/…）
        start_date: 起始日期（检索测试时间窗用）

    Returns:
        [{title, data_source, publish_time, type, snippet, url, symbol, similarity}]
        索引未就绪 / 未配置向量模型 / 无命中返回空列表。
    """
    normalized = normalize_symbol(symbol, market)

    cutoff = end_of_day_ts(as_of) if as_of and len(as_of) <= 10 else parse_publish_ts(as_of)
    floor = parse_publish_ts(start_date) if start_date else None

    conditions = [{"symbol": {"$eq": normalized}}]
    if cutoff is not None:
        conditions.append({"publish_ts": {"$lte": cutoff}})
    if floor is not None:
        conditions.append({"publish_ts": {"$gte": floor}})
    if types:
        conditions.append({"type": {"$in": list(types)}})
    where = {"$and": conditions} if len(conditions) > 1 else conditions[0]

    try:
        query_embedding = embed_texts([query])[0]
    except Exception as e:  # noqa: BLE001 - 检索是增强路径，失败降级为空结果
        logger.warning(f"[kb] 查询向量化失败（{symbol}@{market}）: {e}")
        return []

    try:
        items = vector_store.query(market, query_embedding, n_results=top_k, where=where)
    except Exception as e:  # noqa: BLE001 - 维度不匹配（模型切换未重建）等
        logger.warning(f"[kb] 向量检索失败（{symbol}@{market}，可能需重建索引）: {e}")
        return []

    results: List[Dict] = []
    seen_titles: set = set()
    for item in items:
        # 存量索引中同文档 news/announcement 双档并存：按 (标题, 发布日) 去重，
        # 保相似度更高的前排，top-K 有效容量不受重复挤占
        dedup_key = (item.get("title") or "", str(item.get("publish_time") or "")[:10])
        if dedup_key in seen_titles:
            continue
        seen_titles.add(dedup_key)
        results.append({
            "title": item.get("title") or "",
            "data_source": item.get("data_source") or "",
            "publish_time": item.get("publish_time") or "",
            "type": item.get("type") or "news",
            "snippet": item.get("snippet") or "",
            "url": item.get("url") or "",
            "symbol": item.get("symbol") or normalized,
            "similarity": round(item.get("similarity", 0.0), 4),
        })
    return results
