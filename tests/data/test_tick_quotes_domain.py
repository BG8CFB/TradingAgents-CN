"""tick_quotes 新标准域治理测试（PRD D-6 / FR-06 / T-4）。

覆盖技术方案第六节 15 步清单里可离线验证的部分：
- Schema 字段集与 ``to_db_doc`` 的 None/数组语义
- 域枚举 / 语义类型 / 集合命名 / 唯一键（单版本覆盖，不含 data_source）
- 索引定义与业务集合的一致性（新增域必须同步两处，否则 init_collections 漏建）
- Repo 的 upsert 自然键覆盖、按日删除（保留期清理）、单日计数
- Validator 必填契约（缺 last_price 必须拒写）
- Normalizer 路由与 BaseAdapter 的 NotImplementedError → UNSUPPORTED 语义

测试遵循项目规约：真实代码路径 + 内存 SimulatedMongoDB，禁用 unittest.mock。
``SimulatedMongoCollection`` 不支持 bulk_write，故本文件提供逻辑等价的最小适配
（UpdateOne upsert 语义），与 ``test_qmt_e2e_chain.py`` 中的同名适配一致。
"""

from dataclasses import fields

import pytest

from app.data.storage.mongo.collections import (
    _BUSINESS_COLLECTIONS,
    get_collection_name,
)
from app.data.storage.mongo.index_definitions import (
    INDEX_DEFINITIONS,
    get_unique_key,
)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class TestTickQuotesSchema:
    def test_all_fields_present(self):
        from app.data.schema.domains.tick_quotes import TickQuotesSchema

        names = {f.name for f in fields(TickQuotesSchema)}
        expected = {
            "symbol", "market", "data_source", "updated_at",
            "trade_date", "time_ms", "datetime",
            "last_price", "open", "high", "low", "last_close",
            "volume", "amount", "transaction_num", "market_phase_status",
            "ask_price", "ask_vol", "bid_price", "bid_vol",
        }
        assert expected == names

    def test_to_db_doc_filters_none_but_keeps_arrays(self):
        from app.data.schema.domains.tick_quotes import TickQuotesSchema

        schema = TickQuotesSchema(
            symbol="000001", market="CN", data_source="qmt",
            trade_date="2026-10-20", time_ms=34200000, last_price=11.0,
            ask_price=[11.01, 11.02], ask_vol=[100, 200],
        )
        doc = schema.to_db_doc()
        assert doc["trade_date"] == "2026-10-20"
        assert doc["time_ms"] == 34200000
        assert doc["ask_price"] == [11.01, 11.02]
        assert doc["ask_vol"] == [100, 200]
        # None 值不入库（五档缺档时不产生空键）
        assert "bid_price" not in doc
        assert "bid_vol" not in doc
        assert "open" not in doc
        assert "updated_at" in doc

    def test_storage_name_matches_tech_plan(self):
        from app.data.schema.domains.tick_quotes import TickQuotesSchema

        assert TickQuotesSchema.__name__ == "TickQuotesSchema"


# ---------------------------------------------------------------------------
# 域登记链
# ---------------------------------------------------------------------------


class TestDomainRegistration:
    def test_domain_enum_and_semantics(self):
        from app.data.core.domain import (
            DOMAIN_SEMANTIC_TYPE,
            MARKET_DATA_DOMAINS,
            DataDomain,
            SemanticType,
        )

        assert DataDomain.TICK_QUOTES.value == "tick_quotes"
        assert DOMAIN_SEMANTIC_TYPE[DataDomain.TICK_QUOTES] == SemanticType.TIMESERIES
        # 行情类域：非交易日跳过 + 覆盖率/新鲜度按交易日判定
        assert DataDomain.TICK_QUOTES in MARKET_DATA_DOMAINS

    def test_collection_names_per_market(self):
        assert _BUSINESS_COLLECTIONS["tick_quotes"] == "stock_tick_quotes"
        assert get_collection_name("tick_quotes", "CN") == "stock_tick_quotes"
        assert get_collection_name("tick_quotes", "HK") == "stock_tick_quotes_hk"
        assert get_collection_name("tick_quotes", "US") == "stock_tick_quotes_us"

    def test_unique_key_is_symbol_date_time_ms(self):
        """唯一键三元组：单版本覆盖语义，且绝不能含 data_source。"""
        key = get_unique_key("tick_quotes")
        assert key == ["symbol", "trade_date", "time_ms"]
        assert "data_source" not in key

    def test_index_definitions_cover_new_domain(self):
        """新增域必须同时登记 collections 与 index_definitions。"""
        missing = set(_BUSINESS_COLLECTIONS) - set(INDEX_DEFINITIONS)
        assert not missing, f"缺少索引定义的 domain: {missing}"
        assert "tick_quotes" in INDEX_DEFINITIONS
        # 保留期清理按 trade_date 扫描，必须有该字段的非唯一索引
        has_date_index = any(
            [k for k, _ in idx] == ["trade_date"] and not unique
            for idx, unique in INDEX_DEFINITIONS["tick_quotes"]
        )
        assert has_date_index, "tick_quotes 缺少 trade_date 索引（保留期清理会全表扫描）"

    def test_normalizer_routes_to_adapter_method(self):
        from app.data.processor.normalizer import DOMAIN_METHOD_MAP

        assert DOMAIN_METHOD_MAP["tick_quotes"] == "adapt_tick_quotes"

    def test_validator_requires_price_and_key(self):
        from app.data.processor.validator import Validator

        required = ["symbol", "trade_date", "time_ms", "last_price"]
        good = {
            "symbol": "000001", "market": "CN", "data_source": "qmt",
            "trade_date": "2026-10-20", "time_ms": 34200000, "last_price": 11.0,
        }
        missing_price = {k: v for k, v in good.items() if k != "last_price"}
        missing_time = {k: v for k, v in good.items() if k != "time_ms"}

        valid, errors = Validator().validate(
            [good, missing_price, missing_time], "tick_quotes", "CN"
        )
        assert len(valid) == 1
        assert len(errors) == 2
        joined = " ".join(
            issue for err in errors for issue in err["issues"]
        )
        assert "缺少必填字段: last_price" in joined
        assert "缺少必填字段: time_ms" in joined

    def test_negative_price_rejected(self):
        from app.data.processor.validator import Validator

        rec = {
            "symbol": "000001", "market": "CN", "data_source": "qmt",
            "trade_date": "2026-10-20", "time_ms": 1000, "last_price": -1.0,
        }
        valid, errors = Validator().validate([rec], "tick_quotes", "CN")
        assert not valid
        assert "价格不能为负" in errors[0]["issues"][0]


# ---------------------------------------------------------------------------
# Adapter 契约
# ---------------------------------------------------------------------------


class TestAdapterContract:
    def test_base_adapter_defers_tick_to_subclasses(self):
        from app.data.processor.normalizer import NORMALIZE_UNSUPPORTED, Normalizer
        from app.data.sources.base.adapter import BaseAdapter

        class _NoTickAdapter(BaseAdapter):
            pass

        adapter = _NoTickAdapter(provider=None, market="CN", source_name="tushare")
        result = Normalizer().normalize_with_status(
            [{"symbol": "000001"}], "tick_quotes", adapter
        )
        # 未实现该域的源属于「不支持」而非「数据质量失败」——不误触熔断
        assert result.status == NORMALIZE_UNSUPPORTED
        assert result.records == []

    def test_subclass_override_reaches_normalizer(self):
        from app.data.processor.normalizer import NORMALIZE_OK, Normalizer
        from app.data.schema.domains.tick_quotes import TickQuotesSchema
        from app.data.sources.base.adapter import BaseAdapter

        class _TickAdapter(BaseAdapter):
            def adapt_tick_quotes(self, raw):
                return [
                    TickQuotesSchema(
                        symbol=r["symbol"], market="CN", data_source="qmt",
                        trade_date="2026-10-20", time_ms=r["time_ms"],
                        last_price=r["last_price"],
                    )
                    for r in raw
                ]

        adapter = _TickAdapter(provider=None, market="CN", source_name="qmt")
        result = Normalizer().normalize_with_status(
            [{"symbol": "000001", "time_ms": 1000, "last_price": 11.0}],
            "tick_quotes", adapter,
        )
        assert result.status == NORMALIZE_OK
        assert len(result.records) == 1
        assert result.records[0]["data_source"] == "qmt"
        assert result.records[0]["time_ms"] == 1000


# ---------------------------------------------------------------------------
# Repo（SimulatedMongoDB + 最小 bulk_write 适配）
# ---------------------------------------------------------------------------


class _BulkWriteCollection:
    """SimulatedMongoCollection 的 bulk_write 适配（UpdateOne upsert 语义）。"""

    def __init__(self):
        from test_infra import SimulatedMongoCollection

        self._inner = SimulatedMongoCollection()

    def __getattr__(self, name):
        return getattr(self._inner, name)

    async def bulk_write(self, ops, ordered=False):
        upserted = modified = 0
        for op in ops:
            flt = getattr(op, "_filter", {}) or {}
            doc = getattr(op, "_doc", {}) or {}
            set_doc = doc.get("$set", {})
            existing = await self._inner.find_one(flt)
            if existing is None:
                merged = dict(flt)
                merged.update(set_doc)
                self._inner._insert(merged)
                upserted += 1
            else:
                existing.update(set_doc)
                modified += 1
        return type(
            "Result", (), {"upserted_count": upserted, "modified_count": modified}
        )()


def _install(db, domain: str, market: str = "CN"):
    coll = _BulkWriteCollection()
    db._collections[get_collection_name(domain, market)] = coll
    return coll


def _row(symbol: str, trade_date: str, time_ms: int, price: float = 11.0) -> dict:
    return {
        "symbol": symbol, "market": "CN", "data_source": "qmt",
        "trade_date": trade_date, "time_ms": time_ms, "last_price": price,
    }


@pytest.mark.asyncio
async def test_repo_upsert_same_key_overwrites(inject_sim_db):
    """单版本覆盖：同 symbol+date+time_ms 的备用源写入覆盖原记录。"""
    from app.data.storage.mongo.repositories.tick_quotes_repo import TickQuotesRepo

    coll = _install(inject_sim_db, "tick_quotes")
    repo = TickQuotesRepo()

    first = _row("000001", "2026-10-20", 34200000, 11.0)
    second = _row("000001", "2026-10-20", 34200000, 11.5)
    second["data_source"] = "tushare"

    assert await repo.upsert_many([first], "CN") == 1
    assert await repo.upsert_many([second], "CN") == 1

    docs = await coll.find({"symbol": "000001"}).to_list(length=10)
    assert len(docs) == 1, "同自然键产生多条文档，单版本覆盖语义被破坏"
    assert docs[0]["last_price"] == 11.5
    assert docs[0]["data_source"] == "tushare"


@pytest.mark.asyncio
async def test_repo_skips_records_missing_key(inject_sim_db):
    """缺唯一键字段的记录跳过而非报错（与既有 Repo 同规）。"""
    from app.data.storage.mongo.repositories.tick_quotes_repo import TickQuotesRepo

    _install(inject_sim_db, "tick_quotes")
    repo = TickQuotesRepo()

    bad = _row("000001", "2026-10-20", 1000)
    del bad["time_ms"]
    assert await repo.upsert_many([bad], "CN") == 0
    assert await repo.upsert_many([], "CN") == 0


@pytest.mark.asyncio
async def test_repo_range_query_and_limit(inject_sim_db):
    from app.data.storage.mongo.repositories.tick_quotes_repo import TickQuotesRepo

    coll = _install(inject_sim_db, "tick_quotes")
    repo = TickQuotesRepo()
    await repo.upsert_many(
        [
            _row("000001", "2026-10-17", 34200000),
            _row("000001", "2026-10-20", 1000),
            _row("000001", "2026-10-20", 2000),
            _row("000001", "2026-10-20", 3000),
            _row("600000", "2026-10-20", 1000),
        ],
        "CN",
    )

    full = await repo.get_by_symbol_and_range("000001", "CN", "2026-10-20", "2026-10-20")
    # 单日区间只返回该日记录（SimulatedCursor 的 sort 为空实现，排序正确性
    # 由真实 Mongo 集成用例保证，此处只校验过滤与条数）
    assert sorted(d["time_ms"] for d in full) == [1000, 2000, 3000]

    capped = await repo.get_by_symbol_and_range(
        "000001", "CN", "2026-10-20", "2026-10-20", limit=2
    )
    assert len(capped) == 2
    assert await repo.count_by_date("CN", "2026-10-20") == 4


@pytest.mark.asyncio
async def test_repo_delete_before_date_keeps_retention_window(inject_sim_db):
    """保留期清理（DD-03）：只删 cutoff 之前的分区，返回删除条数供审计。"""
    from app.data.storage.mongo.repositories.tick_quotes_repo import TickQuotesRepo

    coll = _install(inject_sim_db, "tick_quotes")
    repo = TickQuotesRepo()
    await repo.upsert_many(
        [
            _row("000001", "2026-08-01", 1000),
            _row("000001", "2026-08-02", 1000),
            _row("000001", "2026-10-20", 1000),
        ],
        "CN",
    )

    deleted = await repo.delete_before_date("CN", "2026-09-01")
    assert deleted == 2
    remaining = await coll.find({}).to_list(length=10)
    assert [d["trade_date"] for d in remaining] == ["2026-10-20"]