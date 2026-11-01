"""契约测试：read(auto_refresh=...) 行为（阶段 1 已实现，硬断言）。

read(..., auto_refresh=True) 库空时触发补数再读，envelope 含
auto_refreshed 键；不传时保持纯读现状。
"""


from app.data.storage.mongo.collections import get_collection_name

CN_SYM = "900001"
EMPTY_SYM = "000002"  # 库中无数据的目标 symbol


# ============================================================
# 硬测试：不传 auto_refresh 时现状行为
# ============================================================

async def test_read_without_auto_refresh_works(
        inject_sim_db, data_interface):
    """不传 auto_refresh：read 正常返回命中数据（现状签名行为）。"""
    await inject_sim_db[get_collection_name("daily_quotes", "CN")].insert_one(
        {"symbol": CN_SYM, "trade_date": "2026-01-05", "period": "daily",
         "close": 10.0, "data_source": "test"}
    )

    env = await data_interface.read("CN", "daily_quotes", symbol=CN_SYM)

    assert isinstance(env, dict)
    assert env["data"]


# ============================================================
# 硬断言：auto_refresh 下沉（阶段 1 已实现）
# ============================================================

async def test_read_auto_refresh_returns_envelope_key(
        inject_sim_db, data_interface):
    """目标契约：空库上 auto_refresh=True 不抛 TypeError，envelope 含 auto_refreshed。"""
    env = await data_interface.read(
        "CN", "daily_quotes", symbol=EMPTY_SYM, auto_refresh=True,
    )

    assert isinstance(env, dict)
    assert "auto_refreshed" in env
