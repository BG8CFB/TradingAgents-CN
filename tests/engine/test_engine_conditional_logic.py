"""
条件路由逻辑测试
测试 ConditionalLogic 的辩论控制和风险讨论路由逻辑
"""

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def default_logic():
    """默认配置的 ConditionalLogic（1轮辩论，1轮风险讨论）"""
    from app.engine.graph.conditional_logic import ConditionalLogic
    return ConditionalLogic(max_debate_rounds=1, max_risk_discuss_rounds=1)


@pytest.fixture
def multi_round_logic():
    """多轮配置的 ConditionalLogic（3轮辩论，2轮风险讨论）"""
    from app.engine.graph.conditional_logic import ConditionalLogic
    return ConditionalLogic(max_debate_rounds=3, max_risk_discuss_rounds=2)


def _make_debate_state(count, latest_speaker=""):
    """创建模拟的投资辩论状态"""
    return {
        "investment_debate_state": {
            "count": count,
            "latest_speaker": latest_speaker,
        }
    }


def _make_risk_state(count, latest_speaker=""):
    """创建模拟的风险讨论状态"""
    return {
        "risk_debate_state": {
            "count": count,
            "latest_speaker": latest_speaker,
        }
    }


# ---------------------------------------------------------------------------
# Test Classes
# ---------------------------------------------------------------------------

class TestShouldContinueDebate:
    """ConditionalLogic.should_continue_debate 测试"""

    def test_bull_speaker_routes_to_bear(self, default_logic):
        """多头发言后应路由到空头研究员"""
        state = _make_debate_state(count=0, latest_speaker="Bull Researcher")
        result = default_logic.should_continue_debate(state)
        assert result == "Bear Researcher"

    def test_bear_speaker_routes_to_bull(self, default_logic):
        """空头发言后应路由到多头研究员"""
        state = _make_debate_state(count=1, latest_speaker="Bear Researcher")
        result = default_logic.should_continue_debate(state)
        assert result == "Bull Researcher"

    def test_chinese_bull_speaker_routes_to_bear(self, default_logic):
        """中文多头标识应路由到空头"""
        state = _make_debate_state(count=0, latest_speaker="多头研究员")
        result = default_logic.should_continue_debate(state)
        assert result == "Bear Researcher"

    def test_chinese_bear_speaker_routes_to_bull(self, default_logic):
        """中文空头标识应路由到多头"""
        state = _make_debate_state(count=1, latest_speaker="空头研究员")
        result = default_logic.should_continue_debate(state)
        assert result == "Bull Researcher"

    def test_reaches_max_count_routes_to_manager(self, default_logic):
        """达到最大次数应路由到 Research Manager"""
        # max_debate_rounds=1, max_count = 2*(1+1) = 4
        state = _make_debate_state(count=4, latest_speaker="Bull Researcher")
        result = default_logic.should_continue_debate(state)
        assert result == "Research Manager"

    def test_exceeds_max_count_routes_to_manager(self, default_logic):
        """超过最大次数应路由到 Research Manager"""
        state = _make_debate_state(count=5, latest_speaker="Bear Researcher")
        result = default_logic.should_continue_debate(state)
        assert result == "Research Manager"

    def test_unknown_speaker_fallback_even_count(self, default_logic):
        """无法识别发言者时，偶数次路由到多头"""
        state = _make_debate_state(count=2, latest_speaker="Unknown Agent")
        result = default_logic.should_continue_debate(state)
        assert result == "Bull Researcher"

    def test_unknown_speaker_fallback_odd_count(self, default_logic):
        """无法识别发言者时，奇数次路由到空头"""
        state = _make_debate_state(count=3, latest_speaker="Unknown Agent")
        result = default_logic.should_continue_debate(state)
        assert result == "Bear Researcher"

    def test_empty_speaker_fallback(self, default_logic):
        """空发言者应使用奇偶回退逻辑"""
        state = _make_debate_state(count=0, latest_speaker="")
        result = default_logic.should_continue_debate(state)
        # count=0 偶数 → Bull Researcher
        assert result == "Bull Researcher"

    def test_multi_round_max_count(self, multi_round_logic):
        """多轮配置的最大次数应正确计算"""
        # max_debate_rounds=3, max_count = 2*(3+1) = 8
        state = _make_debate_state(count=7, latest_speaker="Bull Researcher")
        result = multi_round_logic.should_continue_debate(state)
        # count=7 < 8, 继续辩论
        assert result == "Bear Researcher"

        state = _make_debate_state(count=8, latest_speaker="Bull Researcher")
        result = multi_round_logic.should_continue_debate(state)
        # count=8 >= 8, 结束辩论
        assert result == "Research Manager"


class TestShouldContinueRiskAnalysis:
    """ConditionalLogic.should_continue_risk_analysis 测试"""

    def test_risky_routes_to_safe(self, default_logic):
        """激进分析师发言后路由到保守分析师"""
        state = _make_risk_state(count=0, latest_speaker="Risky Analyst")
        result = default_logic.should_continue_risk_analysis(state)
        assert result == "Safe Analyst"

    def test_safe_routes_to_neutral(self, default_logic):
        """保守分析师发言后路由到中性分析师"""
        state = _make_risk_state(count=1, latest_speaker="Safe Analyst")
        result = default_logic.should_continue_risk_analysis(state)
        assert result == "Neutral Analyst"

    def test_neutral_routes_to_risky(self, default_logic):
        """中性分析师发言后路由到激进分析师"""
        state = _make_risk_state(count=2, latest_speaker="Neutral Analyst")
        result = default_logic.should_continue_risk_analysis(state)
        assert result == "Risky Analyst"

    def test_reaches_max_count_routes_to_judge(self, default_logic):
        """达到最大次数应路由到 Risk Judge"""
        # max_risk_discuss_rounds=1, max_count = 3*(1+1) = 6
        state = _make_risk_state(count=6, latest_speaker="Risky Analyst")
        result = default_logic.should_continue_risk_analysis(state)
        assert result == "Risk Judge"

    def test_exceeds_max_count_routes_to_judge(self, default_logic):
        """超过最大次数应路由到 Risk Judge"""
        state = _make_risk_state(count=7, latest_speaker="Safe Analyst")
        result = default_logic.should_continue_risk_analysis(state)
        assert result == "Risk Judge"

    def test_multi_round_max_count(self, multi_round_logic):
        """多轮风险讨论的最大次数应正确计算"""
        # max_risk_discuss_rounds=2, max_count = 3*(2+1) = 9
        state = _make_risk_state(count=8, latest_speaker="Neutral Analyst")
        result = multi_round_logic.should_continue_risk_analysis(state)
        # count=8 < 9, 继续讨论
        assert result == "Risky Analyst"

        state = _make_risk_state(count=9, latest_speaker="Neutral Analyst")
        result = multi_round_logic.should_continue_risk_analysis(state)
        # count=9 >= 9, 结束讨论
        assert result == "Risk Judge"

    def test_unknown_prefix_routes_to_risky(self, default_logic):
        """未知前缀应路由到激进分析师"""
        state = _make_risk_state(count=1, latest_speaker="Unknown Speaker")
        result = default_logic.should_continue_risk_analysis(state)
        assert result == "Risky Analyst"

    def test_risk_cycle_order(self, default_logic):
        """风险讨论应按 Risky → Safe → Neutral 循环"""
        speakers = ["Risky Analyst", "Safe Analyst", "Neutral Analyst"]
        expected_next = ["Safe Analyst", "Neutral Analyst", "Risky Analyst"]

        for speaker, expected in zip(speakers, expected_next):
            state = _make_risk_state(count=0, latest_speaker=speaker)
            result = default_logic.should_continue_risk_analysis(state)
            assert result == expected


class TestConditionalLogicInit:
    """ConditionalLogic 初始化测试"""

    def test_default_parameters(self):
        """默认参数应正确设置"""
        from app.engine.graph.conditional_logic import ConditionalLogic

        logic = ConditionalLogic()
        assert logic.max_debate_rounds == 1
        assert logic.max_risk_discuss_rounds == 1

    def test_custom_parameters(self):
        """自定义参数应正确设置"""
        from app.engine.graph.conditional_logic import ConditionalLogic

        logic = ConditionalLogic(max_debate_rounds=5, max_risk_discuss_rounds=3)
        assert logic.max_debate_rounds == 5
        assert logic.max_risk_discuss_rounds == 3


class TestDebateMaxCountCalculation:
    """辩论最大次数计算验证"""

    def test_max_count_formula_for_debate(self):
        """辩论最大次数公式: max_count = 2 * (max_debate_rounds + 1)"""
        from app.engine.graph.conditional_logic import ConditionalLogic

        for rounds in [1, 2, 3, 5]:
            logic = ConditionalLogic(max_debate_rounds=rounds)
            expected_max = 2 * (rounds + 1)
            # 验证在 max_count-1 仍继续，在 max_count 结束
            state_continue = _make_debate_state(count=expected_max - 1, latest_speaker="Bull Researcher")
            state_end = _make_debate_state(count=expected_max, latest_speaker="Bull Researcher")

            assert logic.should_continue_debate(state_continue) == "Bear Researcher"
            assert logic.should_continue_debate(state_end) == "Research Manager"

    def test_max_count_formula_for_risk(self):
        """风险讨论最大次数公式: max_count = 3 * (max_risk_discuss_rounds + 1)"""
        from app.engine.graph.conditional_logic import ConditionalLogic

        for rounds in [1, 2, 3, 5]:
            logic = ConditionalLogic(max_risk_discuss_rounds=rounds)
            expected_max = 3 * (rounds + 1)
            state_continue = _make_risk_state(count=expected_max - 1, latest_speaker="Risky Analyst")
            state_end = _make_risk_state(count=expected_max, latest_speaker="Risky Analyst")

            assert logic.should_continue_risk_analysis(state_continue) == "Safe Analyst"
            assert logic.should_continue_risk_analysis(state_end) == "Risk Judge"
