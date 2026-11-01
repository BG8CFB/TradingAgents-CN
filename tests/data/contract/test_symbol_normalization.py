"""契约测试：symbol 归一化表驱动（阶段 1 已实现，硬断言）。

read 入参容忍多种写法（CN zfill 6 / HK zfill 5 / US 大写），
归一化权威在 app/data/core/symbols.py，envelope.symbol 回显归一化结果。
标准格式硬测试防种子失效造成的假绿。
"""

import pytest

from app.data.storage.mongo.collections import get_collection_name

DATE = "2026-01-05"


async def _seed_daily(db, market: str, symbol: str):
    """向指定市场 daily_quotes 种 1 条标准格式数据。"""
    await db[get_collection_name("daily_quotes", market)].insert_one(
        {"symbol": symbol, "trade_date": DATE, "period": "daily",
         "close": 10.0, "data_source": "test"}
    )


# (market, seed_symbol, query_symbol, expected_symbol)
ALIAS_CASES = [
    pytest.param("CN", "000001", "000001.SZ", "000001", id="cn-suffix"),
    pytest.param("CN", "000001", "1", "000001", id="cn-short"),
    pytest.param("HK", "00700", "00700.HK", "00700", id="hk-suffix"),
    pytest.param("HK", "00700", "700", "00700", id="hk-short"),
    pytest.param("US", "AAPL", "aapl", "AAPL", id="us-lower"),
]

# (market, symbol) — 标准格式硬测试
STANDARD_CASES = [
    pytest.param("CN", "000001", id="cn-standard"),
    pytest.param("HK", "00700", id="hk-standard"),
    pytest.param("US", "AAPL", id="us-standard"),
]


# ============================================================
# 硬测试：标准格式现状可命中（防 xfail 空转的种子有效性证明）
# ============================================================

@pytest.mark.parametrize("market,symbol", STANDARD_CASES)
async def test_read_standard_symbol_hits_seed(
        inject_sim_db, data_interface, market, symbol):
    """标准格式 symbol 直查命中种子，envelope 回显原样。"""
    await _seed_daily(inject_sim_db, market, symbol)

    env = await data_interface.read(market, "daily_quotes", symbol=symbol)

    assert env["data"], "标准格式未命中种子——种子失效，xfail 用例不可信"
    assert all(d["symbol"] == symbol for d in env["data"])
    assert env["symbol"] == symbol


# ============================================================
# 硬断言：别名写法归一化（阶段 1 已实现）
# ============================================================

@pytest.mark.parametrize("market,seed,query,expected", ALIAS_CASES)
async def test_read_accepts_alias_symbols(
        inject_sim_db, data_interface, market, seed, query, expected):
    """目标契约：别名写法归一化后命中种子，envelope.symbol 回显归一化结果。"""
    await _seed_daily(inject_sim_db, market, seed)

    env = await data_interface.read(market, "daily_quotes", symbol=query)

    assert env["data"], f"写法 {query!r} 应归一化为 {expected!r} 命中种子"
    assert env["symbol"] == expected
