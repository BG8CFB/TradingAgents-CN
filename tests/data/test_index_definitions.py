"""索引定义单一事实源测试（真实 MongoDB）。

验证：
1. INDEX_DEFINITIONS 覆盖全部业务 domain（与 collections.py 一致）
2. 全部业务域唯一键不含 data_source（单版本覆盖语义）
3. 三市场集合实际索引与定义等价、无含 data_source 的旧唯一索引残留
4. Repo upsert filter 键与唯一键一致（抽样关键域）
"""

import pytest

from app.data.storage.mongo.collections import (
    _BUSINESS_COLLECTIONS,
    get_all_collections,
    get_collection_name,
)
from app.data.storage.mongo.index_definitions import (
    INDEX_DEFINITIONS,
    default_index_name,
    get_legacy_index_names,
    get_unique_key,
)

pytestmark = pytest.mark.asyncio


# real_mongo_db fixture 由 tests/data/conftest.py 提供（真实 MongoDB 容器）


class TestDefinitionsStatic:
    def test_covers_all_business_domains(self):
        missing = set(_BUSINESS_COLLECTIONS) - set(INDEX_DEFINITIONS)
        assert not missing, f"缺少索引定义的 domain: {missing}"

    def test_unique_keys_exclude_data_source(self):
        """单版本覆盖语义：任何业务域唯一键不得包含 data_source。"""
        for domain in _BUSINESS_COLLECTIONS:
            key = get_unique_key(domain)
            assert "data_source" not in key, f"{domain} 唯一键含 data_source: {key}"

    def test_unique_key_exists_for_every_domain(self):
        for domain in _BUSINESS_COLLECTIONS:
            key = get_unique_key(domain)
            assert key, f"{domain} 无唯一键定义"

    def test_legacy_names_match_old_pattern(self):
        legacy = get_legacy_index_names()
        assert "daily_quotes" in legacy
        assert legacy["daily_quotes"] == ["symbol_1_trade_date_-1_period_1_data_source_1"]
        assert legacy["basic_info"] == ["symbol_1_data_source_1"]


@pytest.mark.integration
class TestCollectionsIndexes:
    """需真实 MongoDB（docker compose -f docker-compose.dev.yml up -d mongodb）。"""

    async def test_init_collections_matches_definitions(self, real_mongo_db):
        from app.data.scripts.init_collections import init_collections

        for market in ("CN", "HK", "US"):
            await init_collections(market)

        db = real_mongo_db
        for market in ("CN", "HK", "US"):
            for domain, collection_name in get_all_collections(market).items():
                info = await db[collection_name].index_information()
                for fields, _unique in INDEX_DEFINITIONS[domain]:
                    name = default_index_name(fields)
                    assert name in info, (
                        f"{collection_name} 缺少索引 {name}"
                    )

    async def test_no_legacy_unique_index_residual(self, real_mongo_db):
        db = real_mongo_db
        legacy = get_legacy_index_names()
        for market in ("CN", "HK", "US"):
            for domain, collection_name in get_all_collections(market).items():
                info = await db[collection_name].index_information()
                for idx_name in legacy.get(domain, []):
                    assert idx_name not in info, (
                        f"{collection_name} 残留废弃唯一索引 {idx_name}"
                    )

    async def test_upsert_overwrites_same_natural_key(self, real_mongo_db):
        """单版本覆盖：同自然键不同 data_source 的 upsert 只保留一份。"""
        from app.data.storage.mongo.repositories.daily_quotes_repo import DailyQuotesRepo

        repo = DailyQuotesRepo()
        market, symbol, td = "CN", "TESTIDX1", "2024-01-05"
        coll = real_mongo_db[get_collection_name("daily_quotes", market)]

        # 清理历史残留（可重复执行）
        await coll.delete_many({"symbol": symbol})

        try:
            await repo.upsert_many([
                {"symbol": symbol, "trade_date": td, "period": "daily",
                 "close": 10.0, "data_source": "tushare"},
                {"symbol": symbol, "trade_date": td, "period": "daily",
                 "close": 11.0, "data_source": "akshare"},
            ], market)
            count = await coll.count_documents(
                {"symbol": symbol, "trade_date": td, "period": "daily"}
            )
            assert count == 1, f"同自然键存在 {count} 份文档，单版本覆盖语义被破坏"
            doc = await coll.find_one({"symbol": symbol})
            assert doc["close"] == 11.0  # 后写入的备用源覆盖
        finally:
            await coll.delete_many({"symbol": symbol})
