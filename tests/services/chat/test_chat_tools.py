"""chat 5 工具真实 I/O 测试 — 种子数据驱动（真实 MongoDB + 真实 DataInterface 路径）。

用 real_mongo_db：FactorScoresRepo.upsert_many 走 bulk_write（模拟库不支持）。
"""
import pytest

pytestmark = pytest.mark.requires_db

from app.data.core.interface import DataInterface
from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name
from app.data.storage.mongo.repositories.factor_scores_repo import FactorScoresRepo
from app.services.chat import tools as chat_tools

SYMBOL = "TESTC001"
DATES = [f"2026-09-{d:02d}" for d in range(1, 11)]


@pytest.fixture
async def chat_tool_env(real_mongo_db):
    """种 1 只股的基础信息/因子/日线/指标；构造真实 DataInterface。"""
    db = get_motor_db()
    await db[get_collection_name("basic_info", "CN")].update_one(
        {"symbol": SYMBOL},
        {"$set": {"symbol": SYMBOL, "market": "CN", "name": "测试股甲",
                  "industry": "银行", "data_source": "test"}},
        upsert=True,
    )
    await FactorScoresRepo().upsert_many([{
        "symbol": SYMBOL, "trade_date": "2026-09-10", "name": "测试股甲", "industry": "银行",
        "bias_ma20": 3.0, "turnover_amp": 2.0, "ret_5d": 5.0,
        "score_short_term": 90.0, "score_balanced": 75.0, "score_value": 40.0,
    }], market="CN")
    q_coll = db[get_collection_name("daily_quotes", "CN")]
    await q_coll.delete_many({"symbol": SYMBOL})
    await q_coll.insert_many([{
        "symbol": SYMBOL, "trade_date": d, "period": "daily", "close": 10.0 + i * 0.1,
        "volume": 1_000_000, "amount": 12_000_000.0, "pct_chg": 1.0, "data_source": "test",
    } for i, d in enumerate(DATES)])
    await db[get_collection_name("daily_indicators", "CN")].update_one(
        {"symbol": SYMBOL, "trade_date": "2026-09-10"},
        {"$set": {"symbol": SYMBOL, "trade_date": "2026-09-10",
                  "pe_ttm": 12.5, "pb": 1.4, "dividend_yield": 3.2, "data_source": "test"}},
        upsert=True,
    )

    DataInterface.reset_instance()
    di = DataInterface()
    yield di
    DataInterface.reset_instance()
    await q_coll.delete_many({"symbol": SYMBOL})
    await db[get_collection_name("basic_info", "CN")].delete_many({"symbol": SYMBOL})
    await db[get_collection_name("factor_scores", "CN")].delete_many({"symbol": SYMBOL})
    await db[get_collection_name("daily_indicators", "CN")].delete_many({"symbol": SYMBOL})


async def test_search_stock_hit_and_miss(chat_tool_env):
    hit = await chat_tools.search_stock("TESTC001")
    assert SYMBOL in hit and "测试股甲" in hit and "银行" in hit

    miss = await chat_tools.search_stock("不存在股票xyz")
    assert "未找到" in miss


async def test_query_stock_factors(chat_tool_env):
    text = await chat_tools.query_stock_factors(SYMBOL)
    assert "2026-09-10" in text
    assert "score_short_term=90" in text
    assert "bias_ma20=3" in text


async def test_run_strategy_screening_list(chat_tool_env):
    """strategy_id=list → 策略清单（内置模板全量）。"""
    text = await chat_tools.run_strategy_screening("list")
    assert "volume_breakout" in text
    assert "策略模板" in text


async def test_run_strategy_screening_unknown_id(chat_tool_env):
    """未知策略 id → ValueError 转友好提示（不抛出）。"""
    text = await chat_tools.run_strategy_screening("no_such_strategy")
    assert "策略执行失败" in text or "无数据" in text


async def test_query_daily_recommendations_always_text(chat_tool_env):
    """有/无当日推荐都返回可读文本（无 → 引导同步话术）。"""
    text = await chat_tools.query_daily_recommendations("")
    assert isinstance(text, str) and text


async def test_query_stock_quotes(chat_tool_env):
    text = await chat_tools.query_stock_quotes(SYMBOL, days=10)
    assert "区间涨跌幅" in text
    assert "pe_ttm=12.5" in text
    assert "2026-09-01" in text and "2026-09-10" in text


async def test_chat_tools_defs_shape():
    """CHAT_TOOLS：5 个、全部只读可并发；参数全标量。"""
    assert len(chat_tools.CHAT_TOOLS) == 5
    names = {t.name for t in chat_tools.CHAT_TOOLS}
    assert names == {
        "search_stock", "query_stock_factors", "run_strategy_screening",
        "query_daily_recommendations", "query_stock_quotes",
    }
    for tool in chat_tools.CHAT_TOOLS:
        assert tool.is_concurrency_safe is True
        for prop in (tool.params_schema.get("properties") or {}).values():
            assert prop.get("type") in ("string", "integer", "number"), (
                f"{tool.name} 参数含非标量类型: {prop}"
            )


def test_result_clip_cap():
    """结果截断：超 2000 字符保留前缀并带截断标记。"""
    long_text = "x" * 3000
    clipped = chat_tools._clip(long_text)
    assert len(clipped) < len(long_text)
    assert clipped.endswith("已截断，可缩小范围后重试）") or "已截断" in clipped
    assert chat_tools._clip("short") == "short"
