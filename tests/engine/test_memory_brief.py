"""fetch_memory_brief 契约测试（memory 写读对称的检索入口）

- memory=None → 空串（调用方决定注入/占位）
- 真实检索（线程池）→ 拼接 recommendation 文本
- 检索异常 → 占位文案，不抛出
"""

import asyncio

from app.engine.agents.utils.memory import fetch_memory_brief


class _RealShapeMemory:
    """与 FinancialSituationMemory.get_memories 同签名的真实替身（禁 mock 规则下允许的真实类替身）"""

    def __init__(self, records=None, error: Exception | None = None):
        self.records = records or []
        self.error = error
        self.queries: list[tuple[str, int]] = []

    def get_memories(self, current_situation, n_matches=1):
        self.queries.append((current_situation, n_matches))
        if self.error:
            raise self.error
        return self.records[:n_matches]


def test_none_memory_returns_empty():
    assert asyncio.run(fetch_memory_brief(None, "situation")) == ""


def test_real_retrieval_joins_recommendations():
    mem = _RealShapeMemory([
        {"recommendation": "上一轮追高被套，建议等待回调。"},
        {"recommendation": "财报季波动放大，注意仓位。"},
        {"recommendation": "应被 n=2 截断的第三条。"},
    ])
    out = asyncio.run(fetch_memory_brief(mem, "A股 白酒 高位", n=2))
    assert "上一轮追高被套" in out and "财报季波动放大" in out
    assert "应被 n=2 截断" not in out
    # 检索参数透传（situation + n_matches）
    assert mem.queries == [("A股 白酒 高位", 2)]


def test_empty_memory_returns_placeholder():
    out = asyncio.run(fetch_memory_brief(_RealShapeMemory([]), "situation"))
    assert out == "暂无历史记忆数据可参考。"


def test_retrieval_failure_degrades_to_placeholder():
    mem = _RealShapeMemory(error=RuntimeError("chroma down"))
    out = asyncio.run(fetch_memory_brief(mem, "situation"))
    assert out == "暂无历史记忆数据可参考。"


def test_empty_situation_short_circuits():
    mem = _RealShapeMemory()
    assert asyncio.run(fetch_memory_brief(mem, "")) == ""
    assert mem.queries == []
