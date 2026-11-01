"""结算→反思→记忆闭环编排测试（真实 MongoDB + ChromaDB 临时集合 + 注入式假 LLM）。

覆盖：反思成功落 memory（metadata.resolution_date == exit_date）、reflection_status
流转与幂等、LLM 失败只置 failed 不回滚结算、retry 护栏。
"""

import uuid
from datetime import date, timedelta

import pytest

from app.data.storage.mongo.collections import get_collection_name
from app.engine.agents.postprocess.reflector import Reflector
from app.engine.agents.utils.memory import FinancialSituationMemory
from app.engine.default_config import DEFAULT_CONFIG
from app.engine.prompts.parts import OUTCOME_REFLECTION_SYSTEM_PROMPT
from app.llm.core.base import BaseLLMClient, StreamEvent
from app.llm.core.types import ChatResponse, Message, Role, StopReason, TextBlock
from app.services.settlement_service import get_settlement_service

pytestmark = pytest.mark.requires_db

FAKE_STOCK = "999994"
MEMORY_COLL = "trader_memory"  # 生产槽位名：测试后按 metadata.symbol 清理本测试写入


class ScriptedLLM(BaseLLMClient):
    """按脚本返回教训或抛错的记录型客户端（真实类，非 mock 库）。

    script 每项：str（返回该文本）或 Exception（抛出）；脚本耗尽即抛
    AssertionError——测试批次的记录数应与脚本严格对齐。
    """

    protocol = "openai"

    def __init__(self, script: list):
        self.model = "scripted-outcome-model"
        self.script = list(script)
        self.calls: list[str] = []

    async def chat(self, messages, *, system=None, tools=None, max_tokens=4096, temperature=None, **kwargs):
        if not self.script:
            raise AssertionError("ScriptedLLM 脚本耗尽（批次的记录数多于脚本）")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        self.calls.append(messages[-1].content)
        assert system == OUTCOME_REFLECTION_SYSTEM_PROMPT
        return ChatResponse(
            message=Message(role=Role.ASSISTANT, content=[TextBlock(text=item)]),
            stop_reason=StopReason.END_TURN,
        )

    async def chat_stream(self, messages, **kwargs):
        resp = await self.chat(messages, **kwargs)
        yield StreamEvent("message", response=resp)

    async def count_tokens(self, messages):
        return 1


def _task_id(prefix: str) -> str:
    return f"test-reflect-{prefix}-{uuid.uuid4().hex[:8]}"


def _summary(signal: str = "Buy", confidence: float = 75.0) -> dict:
    return {
        "final_signal": signal,
        "model_confidence": confidence,
        "key_indicators": {},
        "analysis_summary": "基本面与市场结构共振，短线动能占优。",
    }


async def _seed_rising(db, symbol: str, days: list, start_price: float = 10.0):
    price = start_price
    prev = round(start_price - 0.05, 2)
    closes = {}
    for d in days:
        await db[get_collection_name("daily_quotes", "CN")].update_one(
            {"symbol": symbol, "trade_date": d},
            {
                "$set": {
                    "symbol": symbol,
                    "trade_date": d,
                    "period": "daily",
                    "open": price,
                    "high": round(price + 0.08, 2),
                    "low": round(price - 0.05, 2),
                    "close": round(price + 0.04, 2),
                    "pre_close": prev,
                    "change": 0.05,
                    "pct_chg": 0.5,
                    "volume": 1_000_000.0,
                    "amount": 10_000_000.0,
                }
            },
            upsert=True,
        )
        closes[d] = round(price + 0.04, 2)
        prev = closes[d]
        price = round(price + 0.06, 2)
    return closes


@pytest.fixture(autouse=True)
async def _cleanup(real_mongo_db):
    yield
    db = real_mongo_db
    await db["decision_settlements"].delete_many({"symbol": FAKE_STOCK})
    await db[get_collection_name("daily_quotes", "CN")].delete_many({"symbol": FAKE_STOCK})
    # 清理本测试写入 trader_memory 的文档（按 symbol metadata 精确删）
    try:
        mem = FinancialSituationMemory(MEMORY_COLL, dict(DEFAULT_CONFIG))
        mem.situation_collection.delete(where={"symbol": FAKE_STOCK})
    except Exception:
        pass


@pytest.fixture
async def trade_days(real_mongo_db):
    from app.data.storage.mongo.repositories.trade_calendar_repo import TradeCalendarRepo

    db = real_mongo_db
    end = date.today()
    start = end - timedelta(days=60)
    cal_coll = db[get_collection_name("trade_calendar", "CN")]
    existing = {
        r["cal_date"]
        async for r in cal_coll.find(
            {"exchange": "SSE", "cal_date": {"$gte": start.isoformat(), "$lte": end.isoformat()}},
            {"cal_date": 1},
        )
    }
    missing = [
        {"exchange": "SSE", "cal_date": d.isoformat(), "is_open": True}
        for d in (start + timedelta(days=i) for i in range((end - start).days + 1))
        if d.weekday() < 5 and d.isoformat() not in existing
    ]
    if missing:
        await cal_coll.insert_many(missing)
    rows = await TradeCalendarRepo().get_range("SSE", "CN", start.isoformat(), end.isoformat())
    return sorted(r["cal_date"] for r in rows if r.get("is_open"))


async def _register_and_settle(svc, trade_days, db=None) -> str:
    """种行情 → 登记 → 结算（不种行情记录停在 pending，反思批次查不到）。"""
    if db is not None:
        await _seed_rising(db, FAKE_STOCK, trade_days[-14:])
    task_id = _task_id("ok")
    await svc.register_from_result(
        task_id, "u-test",
        {
            "stock_symbol": FAKE_STOCK, "market_type": "A股",
            "analysis_date": trade_days[-15],
            "structured_summary": _summary("Buy", 80.0),
        },
    )
    await svc.settle_due()
    return task_id


class TestReflectOnSettlements:
    async def test_success_writes_lesson_with_metadata(self, real_mongo_db, trade_days):
        db = real_mongo_db
        svc = get_settlement_service()
        task_id = await _register_and_settle(svc, trade_days, db)
        doc = await db["decision_settlements"].find_one({"task_id": task_id})
        assert doc["status"] == "settled"
        assert doc["reflection_status"] is None

        llm = ScriptedLLM(["教训：高置信 Buy 在 7 日窗口跑赢，延续该路径并校准置信度。"])
        stats = await svc.reflect_on_settlements(reflector_factory=lambda: Reflector(llm))
        assert stats["reflected"] >= 1

        doc = await db["decision_settlements"].find_one({"task_id": task_id})
        assert doc["reflection_status"] == "done"
        assert doc["reflected_at"] is not None
        # 教训写入 trader_memory，resolution_date == exit_date（防前视门槛）
        mem = FinancialSituationMemory(MEMORY_COLL, dict(DEFAULT_CONFIG))
        got = mem.situation_collection.get(where={"symbol": FAKE_STOCK}, include=["metadatas"])
        assert len(got["metadatas"]) >= 1
        meta = got["metadatas"][0]
        assert meta["resolution_date"] == doc["exit_date"]
        assert meta["decision_date"] == doc["decision_date"]
        assert meta["signal"] == "Buy"
        # prompt 里带了真实数字
        assert "80" in llm.calls[0]

    async def test_idempotent_done_not_reprocessed(self, real_mongo_db, trade_days):
        db = real_mongo_db
        svc = get_settlement_service()
        await _register_and_settle(svc, trade_days, db)
        llm = ScriptedLLM(["教训一"])
        await svc.reflect_on_settlements(reflector_factory=lambda: Reflector(llm))
        # 二次 pass：done 记录不再处理（脚本耗尽也不该被调用）
        llm2 = ScriptedLLM([])
        stats = await svc.reflect_on_settlements(reflector_factory=lambda: Reflector(llm2))
        assert stats["reflected"] == 0

    async def test_llm_failure_marks_failed_settlement_intact(self, real_mongo_db, trade_days):
        db = real_mongo_db
        svc = get_settlement_service()
        task_id = await _register_and_settle(svc, trade_days, db)
        llm = ScriptedLLM([RuntimeError("LLM 不可用")])
        stats = await svc.reflect_on_settlements(reflector_factory=lambda: Reflector(llm))
        assert stats["failed"] >= 1

        doc = await db["decision_settlements"].find_one({"task_id": task_id})
        assert doc["reflection_status"] == "failed"
        assert doc["reflection_retry_count"] == 1
        # 结算结果完好（反思失败不回滚）
        assert doc["status"] == "settled"
        assert doc["return_pct"] is not None
        # trader_memory 没有该 symbol 的教训
        mem = FinancialSituationMemory(MEMORY_COLL, dict(DEFAULT_CONFIG))
        got = mem.situation_collection.get(where={"symbol": FAKE_STOCK}, include=["metadatas"])
        assert len(got["metadatas"]) == 0

    async def test_retry_guard_stops_after_three_failures(self, real_mongo_db, trade_days):
        db = real_mongo_db
        svc = get_settlement_service()
        task_id = await _register_and_settle(svc, trade_days, db)
        fail = lambda: Reflector(ScriptedLLM([RuntimeError("boom")]))  # noqa: E731
        for _ in range(4):
            await svc.reflect_on_settlements(reflector_factory=fail)
        doc = await db["decision_settlements"].find_one({"task_id": task_id})
        assert doc["reflection_retry_count"] == 3  # 第 4 次 pass 被 retry 护栏跳过

    async def test_hold_records_skipped(self, real_mongo_db, trade_days):
        """Hold 无对错可总结：不进反思批次。"""
        db = real_mongo_db
        svc = get_settlement_service()
        task_id = _task_id("hold")
        await _seed_rising(db, FAKE_STOCK, trade_days[-14:])
        await svc.register_from_result(
            task_id, "u-test",
            {
                "stock_symbol": FAKE_STOCK, "market_type": "A股",
                "analysis_date": trade_days[-15],
                "structured_summary": _summary("Hold", 55.0),
            },
        )
        await svc.settle_due()
        llm = ScriptedLLM([])
        stats = await svc.reflect_on_settlements(reflector_factory=lambda: Reflector(llm))
        assert stats["reflected"] == 0
        assert stats["failed"] == 0
