# data-access-exempt: 知识库运维面直连（NewsRepo/knowledge 内部件）；阶段 3 收敛到公开契约
"""知识库服务层 — 路由与引擎消费知识库能力的统一入口。

向量索引/检索实现在数据层 app/data/knowledge（公开包）；
本层补齐路由需要的语料概览（news 集合计数属监控面直查）与
同步实现的线程池包装。
"""

import asyncio
import logging
from typing import Dict, List, Optional

from app.data.knowledge import retrieval as kb_retrieval
from app.data.knowledge import vector_store
from app.data.knowledge.config import get_embedding_status
from app.data.knowledge.indexer import MARKETS, load_all_states, rebuild_market, run_incremental

logger = logging.getLogger(__name__)


async def get_overview() -> Dict:
    """三市场语料 + 索引状态 + 向量模型配置概览。"""
    from app.data.storage.mongo.repositories.news_repo import NewsRepo

    repo = NewsRepo()
    states = await load_all_states()
    markets: List[Dict] = []
    for m in MARKETS:
        corpus_count = await repo.count_by_market(m)
        latest_publish = await repo.latest_publish_time(m)
        state = states.get(m) or {}
        markets.append({
            "market": m,
            "corpus_count": corpus_count,
            "indexed_count": vector_store.collection_count(m),
            "latest_publish_time": latest_publish,
            "index_state": {
                "status": state.get("status") or "pending",
                "embedding_model": state.get("embedding_model"),
                "embedding_provider": state.get("embedding_provider"),
                "dimension": state.get("dimension"),
                "checkpoint": state.get("checkpoint"),
                "last_run": state.get("last_run"),
                "last_error": state.get("last_error"),
            },
        })
    return {"markets": markets, "embedding": get_embedding_status()}


async def search(
    market: str,
    symbol: str,
    query: str,
    as_of: Optional[str] = None,
    top_k: int = 6,
    types: Optional[List[str]] = None,
    start_date: Optional[str] = None,
) -> List[Dict]:
    """检索测试入口（同步 Chroma/embedding 调用放线程池）。"""
    return await asyncio.to_thread(
        kb_retrieval.search,
        market, symbol, query,
        as_of=as_of, top_k=top_k, types=types, start_date=start_date,
    )


async def rebuild(market: Optional[str] = None) -> Dict:
    """全量重建（清空集合后按新向量模型签名重扫）。"""
    if market:
        return await rebuild_market(market.upper())
    summary = {}
    for m in MARKETS:
        summary[m] = await rebuild_market(m)
    return summary


async def run_index_now() -> Dict:
    """手动触发一轮增量索引。"""
    return await run_incremental()


def query_citations(
    task_id: Optional[str] = None,
    agent_key: Optional[str] = None,
    limit: int = 100,
) -> List[Dict]:
    """引用校验计数查询（记分卡「引用有效率」数据源）。"""
    from app.data.knowledge import query_citation_stats

    return query_citation_stats(task_id=task_id, agent_key=agent_key, limit=limit)
