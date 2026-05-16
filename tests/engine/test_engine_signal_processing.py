"""
测试 SignalProcessor 信号处理模块

业务逻辑测试：直接调用纯逻辑函数（无需 LLM）
LLM 集成测试：标记 @pytest.mark.ai，使用真实 API
"""

import json
import pytest

from app.engine.graph.signal_processing import SignalProcessor
from app.utils.stock_utils import StockUtils


def _create_sp():
    """创建用于纯逻辑测试的 SignalProcessor（不涉及 LLM 调用）"""
    return SignalProcessor(llm=None)


class TestSignalProcessorInit:
    def test_init_stores_llm(self):
        sp = SignalProcessor(llm="test_llm")
        assert sp.llm == "test_llm"


class TestProcessSignalInvalidInput:
    """process_signal 的无效输入处理（不调用 LLM）"""

    def test_none_input(self):
        sp = _create_sp()
        result = sp.process_signal(None)
        assert result["action"] == "持有"
        assert result["target_price"] is None
        assert result["confidence"] == 0.5

    def test_empty_string_input(self):
        sp = _create_sp()
        result = sp.process_signal("")
        assert result["action"] == "持有"

    def test_whitespace_only_input(self):
        sp = _create_sp()
        result = sp.process_signal("   \n\t  ")
        assert result["action"] == "持有"

    def test_non_string_input(self):
        sp = _create_sp()
        result = sp.process_signal(123)
        assert result["action"] == "持有"


class TestSmartPriceEstimation:
    """价格智能估算纯逻辑"""

    def test_buy_with_current_price_and_percentage(self):
        sp = _create_sp()
        text = "当前价格：10.00，上涨 5.0%"
        result = sp._smart_price_estimation(text, "买入", True)
        assert result == round(10.0 * 1.05, 2)

    def test_sell_with_current_price_and_percentage(self):
        sp = _create_sp()
        text = "现价：20.00，涨幅 10%"
        result = sp._smart_price_estimation(text, "卖出", True)
        assert result == round(20.0 * 0.90, 2)

    def test_buy_with_price_only_china(self):
        sp = _create_sp()
        result = sp._smart_price_estimation("股价：10.00", "买入", True)
        assert result == round(10.0 * 1.15, 2)

    def test_sell_with_price_only_non_china(self):
        sp = _create_sp()
        result = sp._smart_price_estimation("价格：100.00", "卖出", False)
        assert result == round(100.0 * 0.92, 2)

    def test_hold_returns_current_price(self):
        sp = _create_sp()
        result = sp._smart_price_estimation("当前价格：50.00", "持有", True)
        assert result == 50.0

    def test_no_price_info_returns_none(self):
        sp = _create_sp()
        result = sp._smart_price_estimation("无价格信息", "买入", True)
        assert result is None


class TestExtractSimpleDecision:
    """简单决策提取纯逻辑"""

    def test_extract_buy(self):
        sp = _create_sp()
        result = sp._extract_simple_decision("建议买入该股票，目标价位：45.50", True)
        assert result["action"] == "买入"
        assert result["target_price"] == 45.50

    def test_extract_sell(self):
        sp = _create_sp()
        result = sp._extract_simple_decision("建议SELL卖出该股票", True)
        assert result["action"] == "卖出"

    def test_extract_hold(self):
        sp = _create_sp()
        result = sp._extract_simple_decision("建议HOLD持有观望", True)
        assert result["action"] == "持有"

    def test_default_confidence(self):
        sp = _create_sp()
        result = sp._extract_simple_decision("市场中性", True)
        assert result["confidence"] == 0.7

    def test_price_from_yuan_pattern(self):
        sp = _create_sp()
        result = sp._extract_simple_decision("建议买入，价格88.50元", True)
        assert result["target_price"] == 88.50


class TestGetDefaultDecision:
    """默认决策结构测试"""

    def test_returns_correct_structure(self):
        sp = _create_sp()
        result = sp._get_default_decision()
        assert result["action"] == "持有"
        assert result["target_price"] is None
        assert result["confidence"] == 0.5
        assert result["risk_score"] == 0.5
        assert "reasoning" in result


class TestProcessSignalFallback:
    """LLM 不可用时的降级处理"""

    def test_llm_none_falls_back_to_simple(self):
        """LLM 为 None 时降级到简单决策提取"""
        sp = _create_sp()
        result = sp.process_signal("建议买入，目标价位50元", stock_symbol="000001")
        assert result["action"] == "买入"
        assert result["target_price"] == 50.0


class TestProcessSignalWithLLM:
    """
    使用真实 LLM API 的信号处理测试

    标记 @pytest.mark.ai，需要有效的 API Key
    """

    @pytest.mark.ai
    @pytest.mark.asyncio
    def test_buy_signal_with_real_llm(self):
        """使用真实 LLM 处理买入信号"""
        from app.engine.llm_adapters.factory import create_llm
        import os

        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            pytest.skip("需要 DEEPSEEK_API_KEY 环境变量")

        llm = create_llm(provider="deepseek", model="deepseek-chat", api_key=api_key)
        sp = SignalProcessor(llm=llm)
        result = sp.process_signal(
            "基于技术分析，建议买入平安银行，目标价位16.50元",
            stock_symbol="000001",
        )
        assert result["action"] in ("买入", "持有")
        assert isinstance(result["confidence"], float)
        assert 0 <= result["confidence"] <= 1
