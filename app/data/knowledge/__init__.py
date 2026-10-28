"""知识库（stock_news 语料向量化检索）— 数据层公开包。

与记忆集合（FinancialSituationMemory，自身经验）分开：这里是公共事实语料，
按市场独立集合 kb_news_{cn,hk,us} 持久化在 ChromaDB。

分层：
- config.py      向量模型配置解析（OpenAI 兼容 /v1/embeddings）与文本编码
- vector_store.py ChromaDB 持久化集合读写
- indexer.py     增量/全量索引（独立 cron，与结算解耦）
- retrieval.py   向量相似 + where 过滤检索（as_of 防前视）
- stats.py       分析引用校验计数落库（记分卡「引用有效率」数据源）
- util.py        publish_ts 解析 / symbol 归一

消费方（engine / services / routers）只 import 本包公开函数，
不触达包内 ChromaDB / Mongo 细节。
"""

from app.data.knowledge.config import (
    KBEmbeddingNotConfigured,
    get_embedding_config,
    get_embedding_status,
)
from app.data.knowledge.indexer import rebuild_market, run_incremental
from app.data.knowledge.retrieval import search
from app.data.knowledge.stats import query_citation_stats, record_citation_stats
from app.data.knowledge.util import normalize_symbol, parse_publish_ts
from app.data.knowledge.vector_store import collection_count, collection_name

__all__ = [
    "KBEmbeddingNotConfigured",
    "get_embedding_config",
    "get_embedding_status",
    "run_incremental",
    "rebuild_market",
    "search",
    "record_citation_stats",
    "query_citation_stats",
    "normalize_symbol",
    "parse_publish_ts",
    "collection_count",
    "collection_name",
]
