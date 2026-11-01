"""指数日线仓储测试（真实 MongoDB I/O，无 mock）。

数据种在指数规范码上（独立于股票 daily_quotes 集合），清理按 symbol 过滤。
"""

import pytest

from app.data.storage.mongo.collections import get_collection_name
from app.data.storage.mongo.repositories.index_quotes_repo import IndexQuotesRepo

pytestmark = pytest.mark.requires_db

FAKE_INDEX = "999998.SH"  # 未上市指数段，不与真实基准冲突
FAKE_INDEX_HK = "TESTHK"


def _bar(trade_date: str, open_=100.0, close=101.0, pre_close=100.0) -> dict:
    return {
        "symbol": FAKE_INDEX,
        "trade_date": trade_date,
        "open": open_,
        "high": max(open_, close) + 0.5,
        "low": min(open_, close) - 0.5,
        "close": close,
        "pre_close": pre_close,
        "change": round(close - pre_close, 4),
        "pct_chg": round((close - pre_close) / pre_close * 100, 4),
        "volume": 1000.0,
        "amount": 10000.0,
        "data_source": "tushare",
    }


@pytest.fixture(autouse=True)
async def _cleanup(real_mongo_db):
    yield
    db = real_mongo_db
    await db[get_collection_name("index_quotes", "CN")].delete_many({"symbol": FAKE_INDEX})
    await db[get_collection_name("index_quotes", "HK")].delete_many({"symbol": FAKE_INDEX_HK})


class TestIndexQuotesRepo:
    async def test_upsert_single_version_overwrite(self, real_mongo_db):
        repo = IndexQuotesRepo()
        n1 = await repo.upsert_many([_bar("2026-01-05")], "CN")
        assert n1 == 1
        # 同 symbol 同 trade_date 二写只留一份（单版本覆盖）
        await repo.upsert_many([{**_bar("2026-01-05"), "close": 105.0}], "CN")
        coll = real_mongo_db[get_collection_name("index_quotes", "CN")]
        count = await coll.count_documents({"symbol": FAKE_INDEX, "trade_date": "2026-01-05"})
        assert count == 1
        doc = await coll.find_one({"symbol": FAKE_INDEX, "trade_date": "2026-01-05"})
        assert doc["close"] == 105.0

    async def test_get_by_symbol_and_range_sorted(self, real_mongo_db):
        repo = IndexQuotesRepo()
        await repo.upsert_many(
            [_bar("2026-01-07"), _bar("2026-01-05"), _bar("2026-01-06")], "CN"
        )
        rows = await repo.get_by_symbol_and_range(FAKE_INDEX, "CN", "2026-01-05", "2026-01-07")
        assert [r["trade_date"] for r in rows] == ["2026-01-05", "2026-01-06", "2026-01-07"]

    async def test_get_asof_bar_falls_back_to_previous_day(self, real_mongo_db):
        repo = IndexQuotesRepo()
        await repo.upsert_many([_bar("2026-01-05", close=101.0), _bar("2026-01-06", close=102.0)], "CN")
        # 目标日无 bar → 前一交易日
        got = await repo.get_asof_bar(FAKE_INDEX, "CN", "2026-01-07")
        assert got is not None
        trade_date, bar = got
        assert trade_date == "2026-01-06"
        assert bar["close"] == 102.0
        # 早于全部数据 → None
        assert await repo.get_asof_bar(FAKE_INDEX, "CN", "2026-01-01") is None

    async def test_market_collection_suffix(self):
        assert get_collection_name("index_quotes", "CN") == "index_daily_quotes"
        assert get_collection_name("index_quotes", "HK") == "index_daily_quotes_hk"
        assert get_collection_name("index_quotes", "US") == "index_daily_quotes_us"
