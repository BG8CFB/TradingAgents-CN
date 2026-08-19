"""Reader 新读接口测试 — read_latest / read_latest_batch / read_batch / search_basic_info。

真实 MongoDB（docker 容器），自造测试数据（TEST 前缀 symbol），finally 清理。
"""

import pytest

from app.data.core.interface import DataInterface
from app.data.core.reader import Reader

SYMS = ["TEST0001", "TEST0002", "TEST9900"]


async def _insert_fixtures(db):
    """写入测试数据：basic_info / daily_quotes / market_quotes（TEST 前缀）。"""
    basic_coll = db["stock_basic_info"]
    dq_coll = db["stock_daily_quotes"]
    mq_coll = db["market_quotes"]

    for s in SYMS:
        await basic_coll.insert_one({
            "symbol": s, "name": f"测试股票{s}", "market": "主板",
            "exchange": "SSE", "data_source": "tushare",
            "updated_at": "2026-01-01T00:00:00",
        })

    # TEST0001 三条日线（乱序插入，最新为 2026-01-03）；TEST0002 一条
    dq_docs = [
        {"symbol": "TEST0001", "trade_date": "2026-01-03", "close": 13.0,
         "pct_chg": 3.0, "data_source": "tushare", "updated_at": "2026-01-03T18:00:00"},
        {"symbol": "TEST0001", "trade_date": "2026-01-01", "close": 10.0,
         "pct_chg": 1.0, "data_source": "tushare", "updated_at": "2026-01-01T18:00:00"},
        {"symbol": "TEST0001", "trade_date": "2026-01-02", "close": 12.0,
         "pct_chg": 2.0, "data_source": "tushare", "updated_at": "2026-01-02T18:00:00"},
        {"symbol": "TEST0002", "trade_date": "2026-01-02", "close": 20.0,
         "pct_chg": 5.0, "data_source": "tushare", "updated_at": "2026-01-02T18:00:00"},
    ]
    await dq_coll.insert_many(dq_docs)

    await mq_coll.insert_one({
        "symbol": "TEST0001", "close": 13.5, "pct_chg": 3.8,
        "data_source": "tushare", "updated_at": "2026-01-03T15:30:00",
    })


async def _cleanup(db):
    for coll_name in ("stock_basic_info", "stock_daily_quotes", "market_quotes"):
        await db[coll_name].delete_many({"symbol": {"$in": SYMS}})


@pytest.fixture
async def reader_db(real_mongo_db):
    """基于共享真实 MongoDB fixture：写入 TEST 数据，finally 清理。"""
    db = real_mongo_db
    await _cleanup(db)
    await _insert_fixtures(db)
    yield db
    await _cleanup(db)


@pytest.mark.asyncio
async def test_read_latest_returns_latest_by_trade_date(reader_db):
    reader = Reader()
    doc = await reader.read_latest("CN", "daily_quotes", "TEST0001")
    assert doc is not None
    assert doc["trade_date"] == "2026-01-03"
    assert doc["close"] == 13.0
    assert "_id" not in doc


@pytest.mark.asyncio
async def test_read_latest_missing_returns_none(reader_db):
    reader = Reader()
    assert await reader.read_latest("CN", "daily_quotes", "TEST8888") is None


@pytest.mark.asyncio
async def test_read_latest_projection(reader_db):
    reader = Reader()
    doc = await reader.read_latest(
        "CN", "daily_quotes", "TEST0001", projection={"close": 1}
    )
    assert doc is not None
    assert set(doc.keys()) == {"close"}
    assert doc["close"] == 13.0


@pytest.mark.asyncio
async def test_read_latest_batch_per_symbol_latest(reader_db):
    reader = Reader()
    result = await reader.read_latest_batch(
        "CN", "daily_quotes", ["TEST0001", "TEST0002", "TEST8888"]
    )
    assert set(result.keys()) == {"TEST0001", "TEST0002"}
    assert result["TEST0001"]["trade_date"] == "2026-01-03"
    assert result["TEST0002"]["trade_date"] == "2026-01-02"


@pytest.mark.asyncio
async def test_read_latest_batch_over_limit_raises():
    reader = Reader()
    symbols = [f"TEST{i:04d}" for i in range(Reader.MAX_BATCH_SYMBOLS + 1)]
    with pytest.raises(ValueError):
        await reader.read_latest_batch("CN", "daily_quotes", symbols)


@pytest.mark.asyncio
async def test_read_batch_all_records(reader_db):
    reader = Reader()
    docs = await reader.read_batch("CN", "daily_quotes", ["TEST0001"])
    assert len(docs) == 3
    dates = [d["trade_date"] for d in docs]
    assert set(dates) == {"2026-01-01", "2026-01-02", "2026-01-03"}


@pytest.mark.asyncio
async def test_read_batch_sort_and_limit(reader_db):
    reader = Reader()
    docs = await reader.read_batch(
        "CN", "daily_quotes", ["TEST0001"],
        sort=[("trade_date", -1)], limit=1,
    )
    assert len(docs) == 1
    assert docs[0]["trade_date"] == "2026-01-03"


@pytest.mark.asyncio
async def test_read_batch_empty_symbols(reader_db):
    reader = Reader()
    assert await reader.read_batch("CN", "daily_quotes", []) == []


@pytest.mark.asyncio
async def test_search_basic_info_by_symbol_prefix(reader_db):
    reader = Reader()
    docs = await reader.search_basic_info("CN", "TEST0001")
    assert len(docs) == 1
    assert docs[0]["symbol"] == "TEST0001"


@pytest.mark.asyncio
async def test_search_basic_info_by_name_contains(reader_db):
    reader = Reader()
    docs = await reader.search_basic_info("CN", "测试股票")
    assert len(docs) == len(SYMS)


@pytest.mark.asyncio
async def test_search_basic_info_limit(reader_db):
    reader = Reader()
    docs = await reader.search_basic_info("CN", "测试股票", limit=2)
    assert len(docs) == 2


@pytest.mark.asyncio
async def test_search_basic_info_regex_escaped(reader_db):
    reader = Reader()
    # ".*" 等正则元字符应被转义，不会匹配所有记录
    docs = await reader.search_basic_info("CN", ".*")
    assert docs == []


@pytest.mark.asyncio
async def test_data_interface_delegates(reader_db):
    DataInterface.reset_instance()
    di = DataInterface.get_instance()
    try:
        latest = await di.read_latest("CN", "daily_quotes", "TEST0001")
        assert latest is not None and latest["trade_date"] == "2026-01-03"

        batch = await di.read_latest_batch("CN", "daily_quotes", SYMS[:2])
        assert set(batch.keys()) == {"TEST0001", "TEST0002"}

        docs = await di.read_batch("CN", "daily_quotes", ["TEST0002"])
        assert len(docs) == 1

        found = await di.search_basic_info("CN", "TEST9900")
        assert len(found) == 1
    finally:
        DataInterface.reset_instance()
