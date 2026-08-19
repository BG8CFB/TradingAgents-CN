"""TokenUsageRecorder 与用量聚合测试

- recorder：fire-and-forget 写入真 Mongo（integration），失败不抛异常（unit）
- 聚合：by_task/by_agent/缓存 token 汇总、按任务明细（integration，真 Mongo I/O）
"""

import asyncio
import uuid

import pytest

from app.core.database import get_mongo_db
from app.services.token_usage_recorder import PricingCalculator, TokenUsageRecorder
from app.services.usage_statistics_service import usage_statistics_service
from app.llm.core.types import Usage


@pytest.fixture
def recorder():
    return TokenUsageRecorder()


@pytest.fixture
def unique_task_id():
    return f"task_{uuid.uuid4().hex[:12]}"


class TestPricingCalculator:
    def test_no_match_returns_zero(self, tmp_path):
        calc = PricingCalculator(str(tmp_path / "none.json"))
        assert calc.calculate_cost("x", "y", 1000, 1000) == (0.0, "CNY")

    def test_cache_price_fallback_to_input_price(self, tmp_path):
        f = tmp_path / "pricing.json"
        f.write_text(
            '[{"provider":"openai","model_name":"m","input_price_per_1k":1.0,"output_price_per_1k":2.0,"currency":"CNY"}]',
            encoding="utf-8",
        )
        calc = PricingCalculator(str(f))
        # 未配置缓存价 → 缓存 token 按输入价计，总额与纯输入一致
        cost_plain, _ = calc.calculate_cost("openai", "m", 1000, 500)
        cost_cache, _ = calc.calculate_cost("openai", "m", 1000, 500, cache_read_tokens=1000)
        assert cost_plain == pytest.approx(cost_cache)

    def test_cache_discount_price(self, tmp_path):
        f = tmp_path / "pricing.json"
        f.write_text(
            '[{"provider":"anthropic","model_name":"m","input_price_per_1k":1.0,"output_price_per_1k":2.0,'
            '"cache_read_price_per_1k":0.1,"cache_write_price_per_1k":1.25,"currency":"CNY"}]',
            encoding="utf-8",
        )
        calc = PricingCalculator(str(f))
        # 1000 input（其中 600 读缓存、400 写缓存）+ 500 output
        # = 0*1.0 + 600*0.1 + 400*1.25 + 500*2.0 = 60 + 500 + 1000 = 1560 → /1k 换算
        cost, currency = calc.calculate_cost(
            "anthropic", "m", 1000, 500, cache_read_tokens=600, cache_creation_tokens=400
        )
        assert cost == pytest.approx((0 * 1.0 + 600 * 0.1 + 400 * 1.25 + 500 * 2.0) / 1000 * 1000 / 1000)
        # 直接验证公式：均为 per_1k，token 数即按千分之一计价
        expected = (0 / 1000) * 1.0 + (600 / 1000) * 0.1 + (400 / 1000) * 1.25 + (500 / 1000) * 2.0
        assert cost == pytest.approx(expected)
        assert currency == "CNY"


class TestRecorderFireAndForget:
    def test_record_never_raises_without_loop(self, recorder, unique_task_id):
        """无事件循环、无 Mongo：record() 静默成功（不抛异常）"""
        recorder.record(
            provider="openai",
            model_name="test-model",
            usage=Usage(input_tokens=10, output_tokens=5, cache_read_input_tokens=3),
            task_id=unique_task_id,
            user_id="u1",
            agent_key="market_analyst",
            phase="analysts",
        )


async def _with_real_mongo(coro_factory):
    """在独立事件循环中初始化真 Mongo、执行、收尾（对齐 tests/data/conftest.real_mongo_db 模式）"""
    import app.core.database as db_module

    await db_module.db_manager.init_mongodb()
    db_module.mongo_client = db_module.db_manager.mongo_client
    db_module.mongo_db = db_module.db_manager.mongo_db
    try:
        return await coro_factory()
    finally:
        await db_module.db_manager.close_connections()
        db_module.mongo_client = None
        db_module.mongo_db = None


@pytest.mark.integration
@pytest.mark.usefixtures("mongodb_available")
class TestRecorderMongoWrite:
    async def test_record_persists_all_fields(self, recorder, unique_task_id):
        async def _run():
            async def _body():
                recorder.record(
                    provider="openai",
                    model_name="test-model",
                    usage=Usage(input_tokens=100, output_tokens=40, cache_read_input_tokens=60),
                    task_id=unique_task_id,
                    user_id="user_test",
                    agent_key="market_analyst",
                    phase="analysts",
                )
                await asyncio.sleep(0.5)  # fire-and-forget 落库窗口
                db = get_mongo_db()
                doc = await db["token_usage"].find_one({"task_id": unique_task_id})
                await db["token_usage"].delete_many({"task_id": unique_task_id})
                return doc

            return await _with_real_mongo(_body)

        doc = await asyncio.to_thread(asyncio.run, _run())
        assert doc is not None
        assert doc["input_tokens"] == 100
        assert doc["output_tokens"] == 40
        assert doc["cache_read_input_tokens"] == 60
        assert doc["agent_key"] == "market_analyst"
        assert doc["phase"] == "analysts"
        assert doc["user_id"] == "user_test"
        assert doc["session_id"] == unique_task_id
        # 时间戳为 UTC（不带本地时区偏移的 +08:00）
        assert "+08:00" not in doc["timestamp"]


@pytest.mark.integration
@pytest.mark.usefixtures("mongodb_available")
class TestUsageAggregation:
    async def test_task_usage_aggregation(self, unique_task_id):
        async def _run():
            async def _body():
                db = get_mongo_db()
                docs = [
                    {
                        "timestamp": "2026-08-19T08:00:00",
                        "provider": "openai", "model_name": "m1",
                        "input_tokens": 100, "output_tokens": 50,
                        "cache_creation_input_tokens": 10, "cache_read_input_tokens": 70,
                        "cost": 0.1, "currency": "CNY",
                        "session_id": unique_task_id, "analysis_type": "stock_analysis",
                        "task_id": unique_task_id, "user_id": "u_agg",
                        "agent_key": "market_analyst", "phase": "analysts",
                    },
                    {
                        "timestamp": "2026-08-19T08:01:00",
                        "provider": "openai", "model_name": "m1",
                        "input_tokens": 200, "output_tokens": 80,
                        "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                        "cost": 0.2, "currency": "CNY",
                        "session_id": unique_task_id, "analysis_type": "stock_analysis",
                        "task_id": unique_task_id, "user_id": "u_agg",
                        "agent_key": "trader", "phase": "trader",
                    },
                ]
                await db["token_usage"].insert_many(docs)
                try:
                    usage = await usage_statistics_service.get_task_usage(unique_task_id)
                    stats = await usage_statistics_service.get_usage_statistics(days=365)
                finally:
                    await db["token_usage"].delete_many({"task_id": unique_task_id})
                return usage, stats

            return await _with_real_mongo(_body)

        usage, stats = await asyncio.to_thread(asyncio.run, _run())
        assert usage["totals"]["input_tokens"] == 300
        assert usage["totals"]["output_tokens"] == 130
        assert usage["totals"]["cache_read_tokens"] == 70
        agents = {row["agent_key"]: row for row in usage["by_agent"]}
        assert set(agents) == {"market_analyst", "trader"}
        assert agents["market_analyst"]["input_tokens"] == 100
        phases = {row["phase"] for row in usage["by_phase"]}
        assert phases == {"analysts", "trader"}
        # 全局统计包含缓存维度与任务维度
        assert stats.total_cache_read_tokens >= 70
        assert unique_task_id in stats.by_task
