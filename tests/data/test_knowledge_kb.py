"""知识库基础能力测试 — 工具函数与向量存储真实读写。

不依赖外部服务：向量由测试直接构造（真实 I/O，非 mock），
Chroma 持久化目录落在测试进程的 runtime/data/kb_chroma。
"""

import pytest

from app.data.knowledge import vector_store
from app.data.knowledge.util import (
    end_of_day_ts,
    normalize_symbol,
    parse_publish_ts,
)


# ============================================================================
# util: normalize_symbol
# ============================================================================
class TestNormalizeSymbol:
    def test_cn_pads_to_6(self):
        assert normalize_symbol("1", "CN") == "000001"
        assert normalize_symbol("000001", "CN") == "000001"

    def test_cn_strips_exchange_suffix(self):
        assert normalize_symbol("600000.SH", "CN") == "600000"
        assert normalize_symbol("000001.SZ", "CN") == "000001"

    def test_hk_pads_to_5(self):
        assert normalize_symbol("700", "HK") == "00700"
        assert normalize_symbol("00700.HK", "HK") == "00700"

    def test_us_uppercase(self):
        assert normalize_symbol("aapl", "US") == "AAPL"
        assert normalize_symbol("BRK.B", "US") == "BRK.B"

    def test_empty_input_falls_back_to_padding(self):
        # None/空串按空处理：CN 补零为 000000，检索不命中（调用方恒有 symbol）
        assert normalize_symbol(None, "CN") == "000000"
        assert normalize_symbol("", "CN") == "000000"
        assert normalize_symbol(None, "US") == ""


# ============================================================================
# util: parse_publish_ts / end_of_day_ts
# ============================================================================
class TestParsePublishTs:
    def test_iso_with_t(self):
        assert parse_publish_ts("2024-06-01T10:00:00") == 1717236000.0

    def test_space_format(self):
        assert parse_publish_ts("2024-06-01 10:00:00") == 1717236000.0

    def test_date_only(self):
        assert parse_publish_ts("2024-06-01") == 1717200000.0

    def test_invalid_returns_none(self):
        assert parse_publish_ts(None) is None
        assert parse_publish_ts("") is None
        assert parse_publish_ts("not-a-date") is None

    def test_end_of_day_after_noon(self):
        day = parse_publish_ts("2024-06-01")
        eod = end_of_day_ts("2024-06-01")
        assert eod > day
        assert eod - day == 86399.0


# ============================================================================
# vector_store: 真实 Chroma 读写（余弦相似 + where 过滤）
# ============================================================================
@pytest.fixture
def kb_collection():
    """独立集合，测后清理，避免污染真实索引数据。"""
    vector_store.delete_collection("CN")
    yield
    vector_store.delete_collection("CN")


def _meta(symbol: str, publish_ts: float, ctype: str) -> dict:
    return {
        "symbol": symbol,
        "title": f"t-{symbol}-{ctype}",
        "publish_ts": publish_ts,
        "publish_time": "2024-06-01 10:00:00",
        "data_source": "akshare",
        "type": ctype,
        "url": "",
        "embedding_model": "test-model",
        "dimension": 2,
    }


class TestVectorStoreRoundtrip:
    def test_upsert_query_and_similarity_order(self, kb_collection):
        vector_store.upsert_documents(
            "CN",
            ids=["TESTKB:1", "TESTKB:2", "TESTKB:3"],
            documents=["平安银行 业绩", "平安银行 公告", "其它"],
            embeddings=[[1.0, 0.0], [0.7071, 0.7071], [0.0, 1.0]],
            metadatas=[
                _meta("TESTKB", 1717236000.0, "news"),
                _meta("TESTKB", 1717150000.0, "announcement"),
                _meta("TESTKB", 1717060000.0, "news"),
            ],
        )
        assert vector_store.collection_count("CN") == 3

        items = vector_store.query("CN", [1.0, 0.0], n_results=3)
        assert len(items) == 3
        # 余弦相似降序：第一项与查询向量同向
        assert items[0]["similarity"] > items[1]["similarity"] > items[2]["similarity"]
        assert items[0]["similarity"] == pytest.approx(1.0, abs=1e-6)
        assert items[0]["symbol"] == "TESTKB"
        assert "snippet" in items[0]

    def test_where_publish_ts_cutoff(self, kb_collection):
        vector_store.upsert_documents(
            "CN",
            ids=["TESTKB:a", "TESTKB:b"],
            documents=["早", "晚"],
            embeddings=[[1.0, 0.0], [1.0, 0.0]],
            metadatas=[
                _meta("TESTKB", 100.0, "news"),
                _meta("TESTKB", 200.0, "news"),
            ],
        )
        items = vector_store.query(
            "CN", [1.0, 0.0], n_results=5,
            where={"publish_ts": {"$lte": 150.0}},
        )
        assert [i["publish_ts"] for i in items] == [100.0]

    def test_where_compound_filter_as_retrieval_uses(self, kb_collection):
        """retrieval.search 构造的 $and 组合过滤必须被 Chroma 接受。"""
        vector_store.upsert_documents(
            "CN",
            ids=["TESTKB:a", "TESTKB:b", "TESTKB:c"],
            documents=["a", "b", "c"],
            embeddings=[[1.0, 0.0]] * 3,
            metadatas=[
                _meta("TESTKB", 100.0, "news"),
                _meta("TESTKB", 300.0, "announcement"),
                _meta("OTHER", 100.0, "news"),
            ],
        )
        where = {"$and": [
            {"symbol": {"$eq": "TESTKB"}},
            {"publish_ts": {"$lte": 350.0}},
            {"publish_ts": {"$gte": 50.0}},
            {"type": {"$in": ["news", "announcement"]}},
        ]}
        items = vector_store.query("CN", [1.0, 0.0], n_results=5, where=where)
        got = sorted(i["publish_ts"] for i in items)
        assert got == [100.0, 300.0]

    def test_delete_collection_resets_count(self, kb_collection):
        vector_store.upsert_documents(
            "CN", ids=["TESTKB:x"], documents=["x"],
            embeddings=[[1.0, 0.0]], metadatas=[_meta("TESTKB", 1.0, "news")],
        )
        assert vector_store.collection_count("CN") == 1
        assert vector_store.delete_collection("CN") is True
        assert vector_store.collection_count("CN") == 0
