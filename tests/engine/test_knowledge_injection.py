"""知识库注入与引用校验测试 — 注入台账、[序号] 校验、registry 挂接。"""

from app.engine.tools.datasources import knowledge as kb_tool
from app.engine.tools.datasources import registry as ds_registry


def _refs(n: int = 3) -> list:
    return [
        {
            "idx": i,
            "title": f"参考-{i}",
            "data_source": "akshare",
            "publish_time": "2024-06-01 10:00:00",
            "type": "news",
            "snippet": "摘要",
        }
        for i in range(1, n + 1)
    ]


# ============================================================================
# 注入台账（task_id::agent_key 绑定当次注入 top-K）
# ============================================================================
class TestInjectionLedger:
    def test_make_key(self):
        assert kb_tool.make_injection_key("t1", "a1") == "t1::a1"
        assert kb_tool.make_injection_key("", "") == "::"

    def test_record_and_pop_roundtrip(self):
        key = kb_tool.make_injection_key("task-x", "market")
        kb_tool.record_injection(key, _refs())
        popped = kb_tool.pop_injection(key)
        assert popped is not None
        assert len(popped) == 3
        # 台账是一次性的：校验后即弹出，二次取回为 None
        assert kb_tool.pop_injection(key) is None

    def test_pop_unknown_key_returns_none(self):
        assert kb_tool.pop_injection("never::recorded") is None


# ============================================================================
# [序号] 引用校验
# ============================================================================
class TestValidateCitations:
    def test_keeps_valid_strips_invalid(self):
        cleaned, stats = kb_tool.validate_citations("结论A [1] 结论B [9]", _refs())
        assert "[1]" in cleaned
        assert "[9]" not in cleaned
        assert stats["injected_count"] == 3
        assert stats["cited_refs"] == [1]
        assert stats["invalid_citations"] == [9]

    def test_four_digit_years_not_touched(self):
        text = "2023 年报 [2024] 与 [2]"
        cleaned, stats = kb_tool.validate_citations(text, _refs())
        assert "[2024]" in cleaned
        assert "[2]" in cleaned
        assert stats["invalid_count"] == 0

    def test_markdown_links_not_touched(self):
        text = "详见 [1](http://example.com) 和 [7](http://x)"
        cleaned, stats = kb_tool.validate_citations(text, _refs())
        assert "[1](http://example.com)" in cleaned
        assert "[7](http://x)" in cleaned
        assert stats["cited_refs"] == []

    def test_no_references_strips_all(self):
        cleaned, stats = kb_tool.validate_citations("结论 [1] [2]", [])
        assert "[1]" not in cleaned
        assert "[2]" not in cleaned
        assert stats["injected_count"] == 0
        assert stats["invalid_count"] == 2

    def test_out_of_range_index_is_invalid(self):
        cleaned, stats = kb_tool.validate_citations("[0] [3] [10]", _refs())
        # 序号从 1 起：[0]/[10] 越界剔除，[3] 有效保留
        assert "[3]" in cleaned
        assert "[0]" not in cleaned
        assert "[10]" not in cleaned
        assert stats["cited_refs"] == [3]
        assert stats["invalid_citations"] == [0, 10]


# ============================================================================
# DATASOURCE_REGISTRY 挂接
# ============================================================================
class TestRegistrySpec:
    def test_knowledge_base_spec_registered(self):
        spec = next(
            (s for s in ds_registry.DATASOURCE_REGISTRY if s.tool_id == "knowledge_base"),
            None,
        )
        assert spec is not None, "knowledge_base 必须注册在 DATASOURCE_REGISTRY"
        assert spec.domains == ["news"]
        assert set(spec.markets) == {"CN", "HK", "US"}
        assert callable(spec.fn)

    def test_injection_key_builder_from_context(self):
        spec = next(
            (s for s in ds_registry.DATASOURCE_REGISTRY if s.tool_id == "knowledge_base"),
            None,
        )
        builder = spec.inject_args["injection_key"]
        assert callable(builder)
        assert builder({"task_id": "t9", "agent_key": "market"}) == "t9::market"
