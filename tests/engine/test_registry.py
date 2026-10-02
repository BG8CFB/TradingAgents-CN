"""AgentRegistry 等价性测试（P1 验收载体）。

旧四张身份表以字面量誊抄为 golden 期望（誊抄自删除前的 pipeline.py），断言
registry 查询函数与旧表逐项相等——「搬家无漂移」的硬证明。另对照尚未/已切换
的旧实现（builder.report_display_names、_get_non_analyst_mappings）做实时等价
断言：切换前后该对照恒成立。

只读仓库内 YAML 配置，无 Mongo/Redis 依赖。
"""

import pytest

from app.engine.orchestrator import registry
from app.engine.orchestrator.registry import (
    KIND_ANALYST,
    KIND_DEBATER,
    KIND_JUDGE,
    KIND_SUMMARIZER,
    KIND_TRADER,
)

# ── 旧表誊抄（golden 期望；来源 = 删除前的 pipeline.py 四张表）──────────────

OLD_NODE_SLUG_MAP = {
    "Bull Researcher": "bull-researcher",
    "Bear Researcher": "bear-researcher",
    "Research Manager": "research-manager",
    "Trader": "trader",
    "Risky Analyst": "risky-analyst",
    "Safe Analyst": "safe-analyst",
    "Neutral Analyst": "neutral-analyst",
    "Risk Judge": "risk-manager",
}

OLD_NODE_DISPLAY_FALLBACK = {
    "Summary Agent": "报告总结",
}

OLD_NODE_EVENT_KEYS = {
    "Bull Researcher": "researcher_bull",
    "Bear Researcher": "researcher_bear",
    "Research Manager": "research_manager",
    "Trader": "trader",
    "Risky Analyst": "risk_debater_risky",
    "Safe Analyst": "risk_debater_safe",
    "Neutral Analyst": "risk_debater_neutral",
    "Risk Judge": "risk_manager",
    "Summary Agent": "summary",
}

OLD_SLUG_ALIAS_BASES = {
    "trader_investment_plan": "trader",
    "investment_plan": "trader",
    "final_trade_decision": "trader",
    "research_team_decision": "research-manager",
    "risk_management_decision": "risk-manager",
    "risk_manager_decision": "risk-manager",
}

# phase2/3 YAML + summary fallback 的当前中文名（配置改名时应同步更新此期望）
EXPECTED_NAMES = {
    "bull-researcher": "多头研究员",
    "bear-researcher": "空头研究员",
    "research-manager": "研究部主管",
    "trader": "专业交易员",
    "risky-analyst": "激进风险分析师",
    "safe-analyst": "保守风险分析师",
    "neutral-analyst": "中性风险分析师",
    "risk-manager": "首席风控官",
    "summary": "报告总结",
}


class TestEventKeyEquivalence:
    """event_key_for_node ≡ 旧 _NODE_EVENT_KEYS.get(node_name, node_name)"""

    @pytest.mark.parametrize("node_name,expected", sorted(OLD_NODE_EVENT_KEYS.items()))
    def test_builtin_nodes(self, node_name: str, expected: str):
        assert registry.event_key_for_node(node_name) == expected

    def test_unknown_node_falls_back_to_name(self):
        assert registry.event_key_for_node("Nope Node") == "Nope Node"


class TestDisplayNameEquivalence:
    """display_name_for_node ≡ 旧 _resolve_display_names().get(node_name)"""

    @pytest.mark.parametrize("node_name,slug", sorted(OLD_NODE_SLUG_MAP.items()))
    def test_builtin_nodes_resolve_yaml_name(self, node_name: str, slug: str):
        assert registry.display_name_for_node(node_name) == EXPECTED_NAMES[slug]

    def test_summary_fallback(self):
        # Summary 无 slug 配置，走固定 fallback（旧 _NODE_DISPLAY_FALLBACK 唯一条目）
        assert registry.display_name_for_node("Summary Agent") == OLD_NODE_DISPLAY_FALLBACK["Summary Agent"]

    def test_unknown_node_returns_empty(self):
        assert registry.display_name_for_node("Nope Node") == ""


class TestSlugEquivalence:
    """slug_for_node ≡ 旧 _NODE_SLUG_MAP"""

    @pytest.mark.parametrize("node_name,slug", sorted(OLD_NODE_SLUG_MAP.items()))
    def test_builtin_nodes(self, node_name: str, slug: str):
        assert registry.slug_for_node(node_name) == slug


class TestReportTitleEquivalence:
    """report_title ≡ 旧 _report_display_title 解析链（别名 + 后缀探测 + 回退）"""

    @pytest.mark.parametrize("report_key,slug", sorted(OLD_SLUG_ALIAS_BASES.items()))
    def test_alias_chain(self, report_key: str, slug: str):
        # 别名键（不带 _report 后缀的顶层报告键）→ slug 显示名
        assert registry.report_title(report_key) == EXPECTED_NAMES[slug]

    def test_debater_key_without_suffix(self):
        # 辩手报告键为裸键（bull_researcher，无 _report 后缀）
        assert registry.report_title("bull_researcher") == EXPECTED_NAMES["bull-researcher"]

    def test_analyst_suffix_probe(self):
        # 分析师报告键走 slug 化 + "-analyst" 后缀双候选探测
        assert registry.report_title("market_report") == EXPECTED_NAMES.get("market-analyst", "市场技术分析师")

    def test_fallback_chain(self):
        # 未知键：解析失败 → display_name → report_key 原样
        assert registry.report_title("totally_unknown_key", "") == "totally_unknown_key"
        assert registry.report_title("totally_unknown_key", "备选名") == "备选名"


class TestAnalystReportDisplayNames:
    """analyst_report_display_names ≡ builder.report_display_names（实时对照，切换前后恒等）"""

    def test_matches_builder_output(self):
        from app.engine.prompts.builder import report_display_names

        assert registry.analyst_report_display_names() == report_display_names()

    def test_values_carry_report_suffix_label(self):
        names = registry.analyst_report_display_names()
        assert names, "phase1 配置下应至少装配一名分析师"
        assert all(k.endswith("_report") for k in names)
        assert all(v.endswith("报告") for v in names.values())


class TestProgressTextEquivalence:
    """progress_text ≡ 旧 build_node_mapping 查询（非分析师段实时对照）"""

    def test_matches_non_analyst_mappings(self):
        from app.engine.agents.analysts.dynamic_analyst import DynamicAnalystFactory

        old_mappings = DynamicAnalystFactory._get_non_analyst_mappings()
        for node_name, expected in old_mappings.items():
            assert registry.progress_text(node_name) == expected

    def test_analyst_nodes_match_node_mapping(self):
        from app.engine.agents.analysts.dynamic_analyst import DynamicAnalystFactory

        mapping = DynamicAnalystFactory.build_node_mapping()
        analyst_entries = {
            k: v
            for k, v in mapping.items()
            if k.endswith(" Analyst") and v  # 分析师节点（排除 None 的辅助节点）
        }
        assert analyst_entries, "phase1 配置下应存在分析师节点"
        for node_name, expected in analyst_entries.items():
            assert registry.progress_text(node_name) == expected

    def test_auxiliary_nodes_return_none(self):
        # 工具/消息清理辅助节点在旧映射显式置 None → 调用方回退节点名
        assert registry.progress_text("tools_market") is None
        assert registry.progress_text("Msg Clear Market") is None


class TestCompleteness:
    """完备性：9 内置节点六标识非空、别名并集覆盖、动态段覆盖 phase1 全部分析师"""

    def _static_identities(self):
        return [i for i in registry._load_identities() if not i.is_analyst]

    def test_nine_builtin_nodes(self):
        statics = self._static_identities()
        assert len(statics) == 9
        assert {i.slug for i in statics} == set(EXPECTED_NAMES)

    def test_six_identifiers_non_empty(self):
        for identity in self._static_identities():
            assert identity.slug and identity.node_name and identity.internal_key
            assert identity.name and identity.event_key and identity.kind
            assert identity.progress_name
            # summary 无报告键（structured_summary 不在标题解析链），其余节点必有
            if identity.kind != KIND_SUMMARIZER:
                assert identity.report_keys

    def test_report_keys_cover_old_alias_union(self):
        covered = set()
        for identity in self._static_identities():
            covered.update(identity.report_keys)
        # 三处旧别名表并集（pipeline 6 条为全集；report_titles.py 缺的 1 条一并补齐）
        assert set(OLD_SLUG_ALIAS_BASES) <= covered

    def test_kind_assignment(self):
        by_slug = {i.slug: i for i in self._static_identities()}
        assert by_slug["bull-researcher"].kind == KIND_DEBATER
        assert by_slug["bear-researcher"].kind == KIND_DEBATER
        assert by_slug["risky-analyst"].kind == KIND_DEBATER
        assert by_slug["research-manager"].kind == KIND_JUDGE
        assert by_slug["risk-manager"].kind == KIND_JUDGE
        assert by_slug["trader"].kind == KIND_TRADER
        assert by_slug["summary"].kind == KIND_SUMMARIZER

    def test_dynamic_segment_covers_phase1(self):
        from app.engine.agents.analysts.dynamic_analyst import DynamicAnalystFactory

        phase1_slugs = {a["slug"] for a in DynamicAnalystFactory.get_all_agents() if a.get("slug")}
        registry_slugs = {i.slug for i in registry._load_identities() if i.is_analyst}
        assert phase1_slugs == registry_slugs

    def test_analyst_identity_shape(self):
        analysts = [i for i in registry._load_identities() if i.is_analyst]
        assert analysts
        for identity in analysts:
            assert identity.kind == KIND_ANALYST
            assert identity.event_key == identity.internal_key
            assert identity.report_keys == (f"{identity.internal_key}_report",)
            assert identity.node_name == registry.format_analyst_node(identity.internal_key)


class TestDisplayKeyMap:
    """/api/registry/display-names 数据源：前端本地构建键的超集"""

    def test_covers_frontend_alias_table(self):
        keys = registry.all_display_keys()
        trader_name = EXPECTED_NAMES["trader"]
        assert keys["trader_investment_plan"] == trader_name
        assert keys["investment_plan"] == trader_name
        assert keys["final_trade_decision"] == trader_name
        assert keys["research_team_decision"] == EXPECTED_NAMES["research-manager"]
        assert keys["risk_management_decision"] == EXPECTED_NAMES["risk-manager"]
        assert keys["risk_manager_decision"] == EXPECTED_NAMES["risk-manager"]

    def test_four_key_classes_per_slug(self):
        keys = registry.all_display_keys()
        for slug, name in EXPECTED_NAMES.items():
            base = slug.removesuffix("-analyst").replace("-", "_")
            assert keys.get(slug) == name
            assert keys.get(base) == name
            assert keys.get(f"{base}_report") == name
            assert keys.get(f"{base}_analyst") == name

    def test_all_values_non_empty(self):
        for key, name in registry.all_display_keys().items():
            assert key and name, f"键或值为空: {key!r}"

    def test_names_by_slug_superset_of_static(self):
        slug_names = registry.names_by_slug()
        for slug, name in EXPECTED_NAMES.items():
            assert slug_names[slug] == name
