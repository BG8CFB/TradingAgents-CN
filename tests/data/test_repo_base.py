"""MongoBaseRepo 基类契约测试（真实代码路径 + 内存 Mongo，无 mock）。

覆盖治理阶段 3.3 抽取的模板方法：
- upsert_many 覆盖语义：同自然键不同 data_source 两批写入只留一份（键不含 data_source）
- 缺唯一键字段（trade_date / period）的记录跳过
- range_sort_direction 显式契约：money_flow 降序 / daily_quotes 升序全量锁定
- get_latest_date 命中与 miss

说明：
- SimulatedMongoCollection 未实现 bulk_write（内存模拟库历史缺口，
  tests/data/test_sync_checkpoint_fix.py 亦有记载），本文件补齐该方法：
  逐条 UpdateOne 复用模拟集合已有的真实 update_one 路径，仍为内存真实 I/O。
- SimulatedCursor.sort 为 no-op，行序无法在模拟层断言，故排序方向以
  类属性契约锁定；另附 requires_db 层对真实 Mongo 的行序行为断言。
"""

from types import SimpleNamespace

import pytest

from test_infra import SimulatedMongoCollection

from app.data.storage.mongo.collections import get_collection_name
from app.data.storage.mongo.repositories.base import MongoBaseRepo
from app.data.storage.mongo.repositories.daily_quotes_repo import DailyQuotesRepo
from app.data.storage.mongo.repositories.index_quotes_repo import IndexQuotesRepo
from app.data.storage.mongo.repositories.money_flow_repo import MoneyFlowRepo

from app.data.storage.mongo.repositories.adj_factors_repo import AdjFactorsRepo
from app.data.storage.mongo.repositories.daily_indicators_repo import DailyIndicatorsRepo
from app.data.storage.mongo.repositories.factor_scores_repo import FactorScoresRepo
from app.data.storage.mongo.repositories.margin_trading_repo import MarginTradingRepo
from app.data.storage.mongo.repositories.pre_post_market_repo import PrePostMarketRepo
from app.data.storage.mongo.repositories.southbound_holding_repo import SouthboundHoldingRepo

from pymongo import UpdateOne


# ============================================================
# 模拟库 bulk_write 补齐 — UpdateOne 逐条走真实 update_one 路径
# ============================================================

if not hasattr(SimulatedMongoCollection, "bulk_write"):

    async def _sim_bulk_write(self, ops, ordered=False):
        upserted = modified = 0
        for op in ops:
            if not isinstance(op, UpdateOne):
                raise NotImplementedError(
                    f"模拟库 bulk_write 仅支持 UpdateOne，收到 {type(op).__name__}"
                )
            result = await self.update_one(op._filter, op._doc, upsert=op._upsert)
            modified += result.modified_count
            if getattr(result, "upserted_id", None) is not None:
                upserted += 1
        return SimpleNamespace(upserted_count=upserted, modified_count=modified)

    SimulatedMongoCollection.bulk_write = _sim_bulk_write


# ============================================================
# upsert 覆盖语义 — 同自然键不同 data_source 只留一份
# ============================================================

# (domain, repo_cls, 自然键除 symbol/trade_date 外的额外字段)
OVERWRITE_CASES = [
    ("daily_quotes", DailyQuotesRepo, {"period": "daily"}),
    ("index_quotes", IndexQuotesRepo, {}),
    ("money_flow", MoneyFlowRepo, {}),
]


@pytest.mark.parametrize("domain,repo_cls,key_extra", OVERWRITE_CASES)
async def test_upsert_single_version_overwrite(
    inject_sim_db, domain, repo_cls, key_extra
):
    """同自然键两批写入（data_source 不同）只留一份，后写覆盖先写。"""
    symbol = "000001"
    natural_key = {"symbol": symbol, "trade_date": "2026-01-05", **key_extra}
    repo = repo_cls()

    n1 = await repo.upsert_many(
        [{**natural_key, "close": 10.0, "data_source": "tushare"}], "CN"
    )
    assert n1 == 1
    n2 = await repo.upsert_many(
        [{**natural_key, "close": 11.0, "data_source": "akshare"}], "CN"
    )
    assert n2 == 1  # 覆盖不新增

    coll = inject_sim_db[get_collection_name(domain, "CN")]
    assert await coll.count_documents({"symbol": symbol}) == 1
    doc = await coll.find_one({"symbol": symbol})
    assert doc["data_source"] == "akshare"  # 备用源覆盖同自然键（键不含 data_source）
    assert doc["close"] == 11.0


# ============================================================
# 缺唯一键字段的记录跳过
# ============================================================


@pytest.mark.parametrize("domain,repo_cls,key_extra", OVERWRITE_CASES)
async def test_upsert_skips_records_missing_trade_date(
    inject_sim_db, domain, repo_cls, key_extra
):
    """缺 trade_date 的记录跳过，不写库、不计入返回值。"""
    repo = repo_cls()
    records = [
        {"symbol": "000001", "trade_date": "2026-01-05", **key_extra,
         "data_source": "t"},
        {"symbol": "000002", "data_source": "t"},  # 缺 trade_date → 跳过
        {"symbol": "000003", "trade_date": "2026-01-06", **key_extra,
         "data_source": "t"},
    ]
    n = await repo.upsert_many(records, "CN")
    assert n == 2

    coll = inject_sim_db[get_collection_name(domain, "CN")]
    assert await coll.count_documents({}) == 2
    assert await coll.count_documents({"symbol": "000002"}) == 0


async def test_upsert_skips_daily_quotes_missing_period(inject_sim_db):
    """daily_quotes 自然键含 period：缺 period 的记录同样跳过。"""
    repo = DailyQuotesRepo()
    records = [
        {"symbol": "000001", "trade_date": "2026-01-05", "period": "daily"},
        {"symbol": "000001", "trade_date": "2026-01-06"},  # 缺 period → 跳过
    ]
    assert await repo.upsert_many(records, "CN") == 1


# ============================================================
# range_sort_direction 显式契约（模拟层游标不排序，锁类属性声明）
# ============================================================

# 全量锁定使用基类区间方法的域（防排序方向静默漂移）
DIRECTION_CONTRACT = [
    ("daily_quotes", DailyQuotesRepo, 1),        # 升序：K线取尾部最新、周期聚合
    ("index_quotes", IndexQuotesRepo, 1),        # 升序：基准走势按时间正序
    ("adj_factors", AdjFactorsRepo, 1),          # 升序：前复权序列计算
    ("daily_indicators", DailyIndicatorsRepo, -1),   # 降序：最新优先
    ("money_flow", MoneyFlowRepo, -1),           # 降序：资金流展示最新优先
    ("margin_trading", MarginTradingRepo, -1),   # 降序：两融展示最新优先
    ("southbound_holding", SouthboundHoldingRepo, -1),  # 降序：持仓变动展示
    ("pre_post_market", PrePostMarketRepo, -1),  # 降序：盘前盘后展示
    ("factor_scores", FactorScoresRepo, -1),     # 降序：因子快照最新优先
]


@pytest.mark.parametrize("domain,repo_cls,direction", DIRECTION_CONTRACT)
def test_range_sort_direction_declared(domain, repo_cls, direction):
    assert repo_cls.domain == domain
    assert repo_cls.range_sort_direction == direction


def test_base_default_direction_is_ascending():
    assert MongoBaseRepo.range_sort_direction == 1


# ============================================================
# get_by_symbol_and_range 过滤与 extra_query 透传（模拟层）
# ============================================================


async def test_range_filters_and_extra_query(inject_sim_db):
    coll = inject_sim_db[get_collection_name("daily_quotes", "CN")]
    await coll.insert_many([
        {"symbol": "000001", "trade_date": "2026-01-05", "period": "daily"},
        {"symbol": "000001", "trade_date": "2026-01-06", "period": "daily"},
        {"symbol": "000001", "trade_date": "2026-01-07", "period": "week"},
        {"symbol": "000001", "trade_date": "2026-02-01", "period": "daily"},  # 区间外
        {"symbol": "600000", "trade_date": "2026-01-06", "period": "daily"},  # 其它标的
    ])
    repo = DailyQuotesRepo()

    rows = await repo.get_by_symbol_and_range(
        "000001", "CN", "2026-01-01", "2026-01-31", period="daily"
    )
    assert sorted(r["trade_date"] for r in rows) == ["2026-01-05", "2026-01-06"]

    rows_all = await repo.get_by_symbol_and_range(
        "000001", "CN", "2026-01-01", "2026-01-31"
    )
    assert sorted(r["trade_date"] for r in rows_all) == [
        "2026-01-05", "2026-01-06", "2026-01-07",
    ]


# ============================================================
# get_latest_date 命中与 miss（模拟层 find_one 支持排序）
# ============================================================


@pytest.mark.parametrize("repo_cls", [DailyQuotesRepo, MoneyFlowRepo])
async def test_get_latest_date_hit_and_miss(inject_sim_db, repo_cls):
    repo = repo_cls()
    await repo.upsert_many([
        {"symbol": "000001", "trade_date": "2026-01-05", "period": "daily",
         "data_source": "t"},
        {"symbol": "000001", "trade_date": "2026-01-08", "period": "daily",
         "data_source": "t"},
        {"symbol": "000001", "trade_date": "2026-01-06", "period": "daily",
         "data_source": "t"},
    ], "CN")
    # 命中：取最大 trade_date（乱序写入）
    assert await repo.get_latest_date("000001", "CN") == "2026-01-08"
    # miss：无数据返回 None
    assert await repo.get_latest_date("999999", "CN") is None


# ============================================================
# 排序方向行为断言（真实 Mongo 行序，requires_db → integration 层）
# ============================================================

_RP_SYMBOLS = ("TESTRP01", "TESTRP02")
_RP_DATES = ("2026-01-07", "2026-01-05", "2026-01-06")  # 乱序写入


@pytest.mark.requires_db
class TestRangeOrderOnRealMongo:
    @pytest.fixture(autouse=True)
    async def _cleanup_rp_seeds(self, real_mongo_db):
        yield
        for domain in ("daily_quotes", "money_flow"):
            await real_mongo_db[get_collection_name(domain, "CN")].delete_many(
                {"symbol": {"$in": list(_RP_SYMBOLS)}}
            )

    async def test_daily_quotes_ascending(self, real_mongo_db):
        repo = DailyQuotesRepo()
        await repo.upsert_many([
            {"symbol": "TESTRP01", "trade_date": d, "period": "daily",
             "close": 1.0, "data_source": "t"}
            for d in _RP_DATES
        ], "CN")
        rows = await repo.get_by_symbol_and_range(
            "TESTRP01", "CN", "2026-01-01", "2026-01-31"
        )
        assert [r["trade_date"] for r in rows] == [
            "2026-01-05", "2026-01-06", "2026-01-07",
        ]

    async def test_money_flow_descending(self, real_mongo_db):
        repo = MoneyFlowRepo()
        await repo.upsert_many([
            {"symbol": "TESTRP02", "trade_date": d,
             "main_net_inflow": 1.0, "data_source": "t"}
            for d in _RP_DATES
        ], "CN")
        rows = await repo.get_by_symbol_and_range(
            "TESTRP02", "CN", "2026-01-01", "2026-01-31"
        )
        assert [r["trade_date"] for r in rows] == [
            "2026-01-07", "2026-01-06", "2026-01-05",
        ]
