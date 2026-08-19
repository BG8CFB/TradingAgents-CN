"""ScreeningQueryService 测试 — 四阶段筛选查询（从 database_screening_service 迁入后行为对拍）。

真实 MongoDB，自造 TEST 前缀数据，finally 清理。
重点断言：筛选条件、结果合并、排序分页、字段统计、DataInterface.screen 通用查询。
"""

import pytest

from app.data.query.screening_query import ScreeningQueryService
from app.services.database_screening_service import get_database_screening_service

SYMS = ["TEST0001", "TEST0002"]


async def _insert_fixtures(db):
    basic = db["stock_basic_info"]
    indicators = db["stock_daily_indicators"]
    quotes = db["market_quotes"]
    financial = db["stock_financial_data"]

    await basic.insert_many([
        {"symbol": "TEST0001", "name": "低估值测试", "industry": "银行",
         "area": "北京", "market": "主板", "exchange": "SSE",
         "data_source": "tushare", "updated_at": "2026-01-03T18:00:00"},
        {"symbol": "TEST0002", "name": "高估值测试", "industry": "软件",
         "area": "上海", "market": "创业板", "exchange": "SZSE",
         "data_source": "tushare", "updated_at": "2026-01-03T18:00:00"},
    ])

    await indicators.insert_many([
        {"symbol": "TEST0001", "trade_date": "2026-01-02", "pe_ttm": 5.0,
         "pb": 0.8, "total_mv": 100e8, "circ_mv": 80e8,
         "turnover_rate": 1.5, "volume_ratio": 1.0, "roe": 10.0,
         "data_source": "tushare"},
        {"symbol": "TEST0001", "trade_date": "2026-01-03", "pe_ttm": 6.0,
         "pb": 0.9, "total_mv": 110e8, "circ_mv": 90e8,
         "turnover_rate": 1.6, "volume_ratio": 1.1, "roe": 10.5,
         "data_source": "tushare"},
        {"symbol": "TEST0002", "trade_date": "2026-01-03", "pe_ttm": 80.0,
         "pb": 9.0, "total_mv": 300e8, "circ_mv": 250e8,
         "turnover_rate": 5.0, "volume_ratio": 2.0, "roe": 8.0,
         "data_source": "tushare"},
    ])

    await quotes.insert_many([
        {"symbol": "TEST0001", "close": 13.0, "pct_chg": 2.0,
         "amount": 1.3e8, "volume": 9000000, "data_source": "akshare_eastmoney"},
        {"symbol": "TEST0002", "close": 50.0, "pct_chg": 6.0,
         "amount": 5.0e8, "volume": 20000000, "data_source": "akshare_eastmoney"},
    ])

    await financial.insert_many([
        {"symbol": "TEST0001", "report_period": "2025Q4", "roe": 11.0,
         "data_source": "tushare"},
        {"symbol": "TEST0002", "report_period": "2025Q3", "roe": 7.0,
         "data_source": "tushare"},
    ])


async def _cleanup(db):
    for coll_name in ("stock_basic_info", "stock_daily_indicators",
                      "market_quotes", "stock_financial_data"):
        await db[coll_name].delete_many({"symbol": {"$in": SYMS}})


@pytest.fixture
async def screening_db(real_mongo_db):
    """基于共享真实 MongoDB fixture：写入 TEST 数据，finally 清理。"""
    db = real_mongo_db
    await _cleanup(db)
    await _insert_fixtures(db)
    yield db
    await _cleanup(db)


@pytest.mark.asyncio
async def test_screen_stocks_indicator_condition(screening_db):
    svc = ScreeningQueryService()
    items, total = await svc.screen_stocks(
        conditions=[{"field": "pe", "operator": "<", "value": 10}],
        source="tushare",
    )
    assert total == 1
    assert items[0]["symbol"] == "TEST0001"
    # 最新一行的指标（2026-01-03）
    assert items[0]["pe"] == 6.0
    # total_mv 元 → 亿元转换
    assert items[0]["total_mv"] == 110.0


@pytest.mark.asyncio
async def test_screen_stocks_basic_condition_intersection(screening_db):
    svc = ScreeningQueryService()
    items, total = await svc.screen_stocks(
        conditions=[
            {"field": "pe", "operator": "<", "value": 100},
            {"field": "industry", "operator": "==", "value": "软件"},
        ],
        source="tushare",
    )
    assert total == 1
    assert items[0]["symbol"] == "TEST0002"


@pytest.mark.asyncio
async def test_screen_stocks_merge_and_sort(screening_db):
    svc = ScreeningQueryService()
    items, total = await svc.screen_stocks(
        conditions=[{"field": "pe", "operator": "<", "value": 100}],
        order_by=[{"field": "pe", "direction": "desc"}],
        source="tushare",
    )
    assert total == 2
    assert [i["symbol"] for i in items] == ["TEST0002", "TEST0001"]
    # 行情富集
    assert items[0]["close"] == 50.0
    # ROE 优先取 financial_data（TEST0002: 2025Q3 → 7.0）
    assert items[0]["roe"] == 7.0
    # basic_info 字段
    assert items[1]["name"] == "低估值测试"
    assert items[1]["industry"] == "银行"


@pytest.mark.asyncio
async def test_screen_stocks_pagination(screening_db):
    svc = ScreeningQueryService()
    items, total = await svc.screen_stocks(
        conditions=[{"field": "pe", "operator": "<", "value": 100}],
        limit=1, offset=1,
        order_by=[{"field": "pe", "direction": "asc"}],
        source="tushare",
    )
    assert total == 2
    assert len(items) == 1
    assert items[0]["symbol"] == "TEST0002"


@pytest.mark.asyncio
async def test_thin_shell_same_behavior(screening_db):
    """薄壳 DatabaseScreeningService 与 ScreeningQueryService 输出一致（对拍）。"""
    conditions = [{"field": "pe", "operator": "<", "value": 100}]
    shell = get_database_screening_service()
    query = ScreeningQueryService()
    shell_items, shell_total = await shell.screen_stocks(
        conditions=conditions, order_by=[{"field": "pe", "direction": "asc"}],
        source="tushare",
    )
    query_items, query_total = await query.screen_stocks(
        conditions=conditions, order_by=[{"field": "pe", "direction": "asc"}],
        source="tushare",
    )
    assert shell_total == query_total == 2
    assert shell_items == query_items


@pytest.mark.asyncio
async def test_get_field_statistics(screening_db):
    svc = ScreeningQueryService()
    stats = await svc.get_field_statistics("pe")
    # 每股取最新一行：TEST0001=6.0, TEST0002=80.0
    assert stats["count"] == 2
    assert stats["min"] == 6.0
    assert stats["max"] == 80.0


@pytest.mark.asyncio
async def test_get_available_values(screening_db):
    svc = ScreeningQueryService()
    values = await svc.get_available_values("industry")
    assert set(values) >= {"银行", "软件"}


@pytest.mark.asyncio
async def test_data_interface_screen(screening_db):
    from app.data.core.interface import DataInterface

    DataInterface.reset_instance()
    di = DataInterface.get_instance()
    try:
        result = await di.screen(
            "CN", "basic_info",
            filters={"symbol": {"$in": SYMS}},
            projection={"symbol": 1, "name": 1},
            sort=[("symbol", 1)],
        )
        assert result["total"] == 2
        assert len(result["items"]) == 2
        assert set(result["items"][0].keys()) == {"symbol", "name"}

        paged = await di.screen("CN", "basic_info",
                                filters={"symbol": {"$in": SYMS}},
                                skip=1, limit=1, sort=[("symbol", 1)])
        assert len(paged["items"]) == 1
        assert paged["items"][0]["symbol"] == "TEST0002"
    finally:
        DataInterface.reset_instance()
