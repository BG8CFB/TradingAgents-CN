"""记忆 as_of 防前视过滤测试（纯函数 + 真实 ChromaDB 临时集合，无 mock）。

_filter_visible_asof：结算教训带 resolution_date（结果可知日），历史日期
分析（as_of 早于 resolution_date）不得看到当时尚未揭晓的教训；无日期的
存量文档（P4-b 组件反思写入）默认可见。
"""

import uuid

from app.engine.agents.utils.memory import (
    FinancialSituationMemory,
    _filter_visible_asof,
)
from app.engine.default_config import DEFAULT_CONFIG

COLL_PREFIX = "test_mem_asof_"


class TestFilterVisibleAsof:
    def test_no_resolution_date_visible(self):
        """无 resolution_date（存量/P4-b 文档）→ 可见（不误杀）"""
        items = [{"recommendation": "旧组件教训"}]
        assert _filter_visible_asof(items, "2026-01-01", 5) == items

    def test_resolved_before_asof_visible(self):
        items = [
            {"recommendation": "a", "resolution_date": "2026-01-05"},
            {"recommendation": "b", "resolution_date": "2026-01-10 15:00:00"},  # 带时间也按日比较
        ]
        out = _filter_visible_asof(items, "2026-01-15", 5)
        assert len(out) == 2

    def test_resolved_after_asof_hidden(self):
        items = [
            {"recommendation": "已揭晓", "resolution_date": "2026-01-05"},
            {"recommendation": "未揭晓", "resolution_date": "2026-02-01"},
        ]
        out = _filter_visible_asof(items, "2026-01-15", 5)
        assert [m["recommendation"] for m in out] == ["已揭晓"]

    def test_truncates_to_n(self):
        items = [{"recommendation": str(i)} for i in range(8)]
        assert len(_filter_visible_asof(items, "2026-01-01", 3)) == 3

    def test_exact_boundary_visible(self):
        items = [{"recommendation": "x", "resolution_date": "2026-01-15"}]
        assert _filter_visible_asof(items, "2026-01-15", 5) == items


class TestChromaMetadataRoundtrip:
    async def test_add_with_metadata_and_count(self):
        """add_situations 携带 metadata_list 落盘（真实 ChromaDB 临时集合）。"""
        coll_name = f"{COLL_PREFIX}{uuid.uuid4().hex[:8]}"
        mem = FinancialSituationMemory(coll_name, dict(DEFAULT_CONFIG))
        try:
            before = mem.situation_collection.count()
            mem.add_situations(
                [("平安银行 Buy 复盘", "教训：跑赢基准")],
                metadata_list=[
                    {
                        "decision_date": "2026-10-01",
                        "resolution_date": "2026-10-12",
                        "symbol": "000001",
                        "signal": "Buy",
                        "user_id": "u1",
                    }
                ],
            )
            assert mem.situation_collection.count() == before + 1
            got = mem.situation_collection.get(include=["metadatas"])
            meta = got["metadatas"][0]
            assert meta["recommendation"] == "教训：跑赢基准"
            assert meta["resolution_date"] == "2026-10-12"
            assert meta["symbol"] == "000001"
            assert meta["signal"] == "Buy"
        finally:
            try:
                mem.chroma_manager._client.delete_collection(coll_name)
            except Exception:
                pass

    async def test_add_without_metadata_backward_compatible(self):
        """不传 metadata_list 的旧用法不受影响（仅 recommendation）。"""
        coll_name = f"{COLL_PREFIX}{uuid.uuid4().hex[:8]}"
        mem = FinancialSituationMemory(coll_name, dict(DEFAULT_CONFIG))
        try:
            mem.add_situations([("情景文本", "建议文本")])
            got = mem.situation_collection.get(include=["metadatas"])
            assert got["metadatas"][0]["recommendation"] == "建议文本"
            assert "resolution_date" not in got["metadatas"][0]
        finally:
            try:
                mem.chroma_manager._client.delete_collection(coll_name)
            except Exception:
                pass
