"""契约基线（阶段 0）：read / read_latest 返回形状不变式。

- 硬测试：现状已成立的形状不变式（2026-11-01 探查脚本实证）。
- xfail(strict)：阶段 1 形状钳制目标，实现后 XPASS 即提醒移除标记。

现状与目标契约的关键差异（探查实证，app/data/core/reader.py get_data）：
- 列表语义域（daily_quotes 等）空结果现状返回 data=None——get_data 末尾的
  `if not data` 把空列表统一吞成 None；目标契约为 data=[]。
- basic_info+symbol 单例语义现状已符合目标契约（命中 Dict / 空 None）。
"""


from app.data.storage.mongo.collections import get_collection_name

CN_SYM = "900001"
DATES = ["2026-01-05", "2026-01-06", "2026-01-07"]


async def _seed_cn(db):
    """种 CN daily_quotes（3 条）+ basic_info（1 条）。"""
    await db[get_collection_name("daily_quotes", "CN")].insert_many([
        {"symbol": CN_SYM, "trade_date": d, "period": "daily",
         "close": 10.0, "data_source": "test"}
        for d in DATES
    ])
    await db[get_collection_name("basic_info", "CN")].insert_one(
        {"symbol": CN_SYM, "market": "CN", "name": "契约形状测试股",
         "data_source": "test"})


# ============================================================
# 硬测试：现状已成立的形状不变式
# ============================================================

async def test_read_hit_returns_envelope_with_list_data(
        inject_sim_db, data_interface):
    """命中：envelope 为 dict 含 5 个标准键，data 为非空 List[Dict]。"""
    await _seed_cn(inject_sim_db)

    env = await data_interface.read("CN", "daily_quotes", symbol=CN_SYM)

    assert isinstance(env, dict)
    assert {"data", "freshness", "market", "symbol", "domain"} <= set(env)
    assert isinstance(env["data"], list) and env["data"]
    for item in env["data"]:
        assert isinstance(item, dict)
        assert "symbol" in item and "trade_date" in item


async def test_read_basic_info_symbol_hit_returns_dict(
        inject_sim_db, data_interface):
    """basic_info+symbol 单例语义命中：data 为 Dict。"""
    await _seed_cn(inject_sim_db)

    env = await data_interface.read("CN", "basic_info", symbol=CN_SYM)

    assert isinstance(env["data"], dict)
    assert env["data"]["symbol"] == CN_SYM


async def test_read_basic_info_symbol_miss_returns_none(
        inject_sim_db, data_interface):
    """basic_info+symbol 单例语义空结果：现状已符合契约（None，非 {} 或 []）。"""
    await _seed_cn(inject_sim_db)

    env = await data_interface.read("CN", "basic_info", symbol="999999")

    assert env["data"] is None


async def test_read_basic_info_all_returns_list(
        inject_sim_db, data_interface):
    """basic_info 全量查询（不传 symbol）：data 为 List。"""
    await _seed_cn(inject_sim_db)

    env = await data_interface.read("CN", "basic_info")

    assert isinstance(env["data"], list)
    assert len(env["data"]) == 1
    assert env["data"][0]["symbol"] == CN_SYM


async def test_read_latest_returns_dict_or_none(
        inject_sim_db, data_interface):
    """read_latest：命中返回最新一条 Dict，空返回 None。"""
    await _seed_cn(inject_sim_db)

    hit = await data_interface.read_latest("CN", "daily_quotes", CN_SYM)
    assert isinstance(hit, dict)
    assert hit["trade_date"] == DATES[-1]

    miss = await data_interface.read_latest("CN", "daily_quotes", "999999")
    assert miss is None


# ============================================================
# 硬断言：形状钳制（阶段 1 已实现）
# ============================================================

async def test_read_daily_quotes_empty_range_returns_empty_list(
        inject_sim_db, data_interface):
    """目标契约：查不到的日期范围 → data == []（探查实证现状为 None）。"""
    await _seed_cn(inject_sim_db)

    env = await data_interface.read(
        "CN", "daily_quotes", symbol=CN_SYM,
        start_date="2001-01-01", end_date="2001-01-31",
    )

    assert env["data"] == []


async def test_read_basic_info_empty_collection_returns_empty_list(
        inject_sim_db, data_interface):
    """目标契约：空集合全量查询 → data == []（get_data 把空列表吞成 None）。"""
    env = await data_interface.read("CN", "basic_info")

    assert env["data"] == []
