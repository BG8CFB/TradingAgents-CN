"""测试 SignalProcessor 信号处理模块"""

import json
import pytest
from unittest.mock import MagicMock, patch

from app.engine.graph.signal_processing import SignalProcessor


class TestSignalProcessorInit:
    def test_init_stores_llm(self, mock_llm):
        sp = SignalProcessor(mock_llm)
        assert sp.quick_thinking_llm is mock_llm


class TestProcessSignalInvalidInput:
    def test_none_input(self, mock_llm):
        sp = SignalProcessor(mock_llm)
        result = sp.process_signal(None)
        assert result["action"] == "持有"
        assert result["target_price"] is None
        assert result["confidence"] == 0.5

    def test_empty_string_input(self, mock_llm):
        sp = SignalProcessor(mock_llm)
        result = sp.process_signal("")
        assert result["action"] == "持有"

    def test_whitespace_only_input(self, mock_llm):
        sp = SignalProcessor(mock_llm)
        result = sp.process_signal("   \n\t  ")
        assert result["action"] == "持有"

    def test_non_string_input(self, mock_llm):
        sp = SignalProcessor(mock_llm)
        result = sp.process_signal(123)
        assert result["action"] == "持有"


class TestProcessSignalWithLLM:
    def _make_llm_with_json(self, data):
        llm = MagicMock()
        resp = MagicMock()
        resp.content = json.dumps(data, ensure_ascii=False)
        llm.invoke.return_value = resp
        return llm

    def test_buy_action_normalized(self):
        llm = self._make_llm_with_json({
            "action": "buy",
            "target_price": 45.50,
            "confidence": 0.8,
            "risk_score": 0.3,
            "reasoning": "看好",
        })
        sp = SignalProcessor(llm)
        with patch("app.utils.stock_utils.StockUtils.get_market_info", return_value={
            "is_china": True, "is_hk": False, "currency_name": "人民币",
            "currency_symbol": "¥", "market_name": "A股",
        }):
            result = sp.process_signal("推荐买入", stock_symbol="000001")
        assert result["action"] == "买入"
        assert result["target_price"] == 45.50

    def test_sell_action_normalized(self):
        llm = self._make_llm_with_json({
            "action": "sell",
            "target_price": 30.0,
            "confidence": 0.6,
            "risk_score": 0.7,
            "reasoning": "看空",
        })
        sp = SignalProcessor(llm)
        with patch("app.utils.stock_utils.StockUtils.get_market_info", return_value={
            "is_china": True, "is_hk": False, "currency_name": "人民币",
            "currency_symbol": "¥", "market_name": "A股",
        }):
            result = sp.process_signal("建议卖出", stock_symbol="000001")
        assert result["action"] == "卖出"

    def test_hold_action_unchanged(self):
        llm = self._make_llm_with_json({
            "action": "hold",
            "target_price": 40.0,
            "confidence": 0.7,
            "risk_score": 0.5,
            "reasoning": "中性",
        })
        sp = SignalProcessor(llm)
        with patch("app.utils.stock_utils.StockUtils.get_market_info", return_value={
            "is_china": True, "is_hk": False, "currency_name": "人民币",
            "currency_symbol": "¥", "market_name": "A股",
        }):
            result = sp.process_signal("持有", stock_symbol="000001")
        assert result["action"] == "持有"

    def test_chinese_action_variants(self):
        llm = self._make_llm_with_json({
            "action": "购买",
            "target_price": 50.0,
            "confidence": 0.9,
            "risk_score": 0.2,
            "reasoning": "强烈看好",
        })
        sp = SignalProcessor(llm)
        with patch("app.utils.stock_utils.StockUtils.get_market_info", return_value={
            "is_china": True, "is_hk": False, "currency_name": "人民币",
            "currency_symbol": "¥", "market_name": "A股",
        }):
            result = sp.process_signal("购买建议", stock_symbol="000001")
        assert result["action"] == "买入"

    def test_unknown_action_defaults_to_hold(self):
        llm = self._make_llm_with_json({
            "action": "unknown_action",
            "target_price": 40.0,
            "confidence": 0.7,
            "risk_score": 0.5,
            "reasoning": "未知",
        })
        sp = SignalProcessor(llm)
        with patch("app.utils.stock_utils.StockUtils.get_market_info", return_value={
            "is_china": True, "is_hk": False, "currency_name": "人民币",
            "currency_symbol": "¥", "market_name": "A股",
        }):
            result = sp.process_signal("信号", stock_symbol="000001")
        assert result["action"] == "持有"

    def test_target_price_string_cleanup(self):
        llm = self._make_llm_with_json({
            "action": "买入",
            "target_price": "¥45.50元",
            "confidence": 0.8,
            "risk_score": 0.3,
            "reasoning": "目标价45.50",
        })
        sp = SignalProcessor(llm)
        with patch("app.utils.stock_utils.StockUtils.get_market_info", return_value={
            "is_china": True, "is_hk": False, "currency_name": "人民币",
            "currency_symbol": "¥", "market_name": "A股",
        }):
            result = sp.process_signal("信号", stock_symbol="000001")
        assert isinstance(result["target_price"], float)
        assert result["target_price"] == 45.50

    def test_target_price_none_falls_back_to_text_extraction(self):
        llm = self._make_llm_with_json({
            "action": "买入",
            "target_price": None,
            "confidence": 0.8,
            "risk_score": 0.3,
            "reasoning": "目标价位：88.50",
        })
        sp = SignalProcessor(llm)
        with patch("app.utils.stock_utils.StockUtils.get_market_info", return_value={
            "is_china": True, "is_hk": False, "currency_name": "人民币",
            "currency_symbol": "¥", "market_name": "A股",
        }):
            result = sp.process_signal("信号", stock_symbol="000001")
        assert result["target_price"] == 88.50

    def test_confidence_and_risk_score_are_floats(self):
        llm = self._make_llm_with_json({
            "action": "买入",
            "target_price": 50,
            "confidence": 0.85,
            "risk_score": 0.25,
            "reasoning": "测试",
        })
        sp = SignalProcessor(llm)
        with patch("app.utils.stock_utils.StockUtils.get_market_info", return_value={
            "is_china": True, "is_hk": False, "currency_name": "人民币",
            "currency_symbol": "¥", "market_name": "A股",
        }):
            result = sp.process_signal("信号", stock_symbol="000001")
        assert isinstance(result["confidence"], float)
        assert isinstance(result["risk_score"], float)


class TestSmartPriceEstimation:
    def test_buy_with_current_price_and_percentage(self, mock_llm):
        sp = SignalProcessor(mock_llm)
        text = "当前价格：10.00，上涨 5.0%"
        result = sp._smart_price_estimation(text, "买入", True)
        assert result == round(10.0 * 1.05, 2)

    def test_sell_with_current_price_and_percentage(self, mock_llm):
        sp = SignalProcessor(mock_llm)
        text = "现价：20.00，涨幅 10%"
        result = sp._smart_price_estimation(text, "卖出", True)
        assert result == round(20.0 * 0.90, 2)

    def test_buy_with_price_only_china(self, mock_llm):
        sp = SignalProcessor(mock_llm)
        result = sp._smart_price_estimation("股价：10.00", "买入", True)
        assert result == round(10.0 * 1.15, 2)

    def test_sell_with_price_only_non_china(self, mock_llm):
        sp = SignalProcessor(mock_llm)
        result = sp._smart_price_estimation("价格：100.00", "卖出", False)
        assert result == round(100.0 * 0.92, 2)

    def test_hold_returns_current_price(self, mock_llm):
        sp = SignalProcessor(mock_llm)
        result = sp._smart_price_estimation("当前价格：50.00", "持有", True)
        assert result == 50.0

    def test_no_price_info_returns_none(self, mock_llm):
        sp = SignalProcessor(mock_llm)
        result = sp._smart_price_estimation("无价格信息", "买入", True)
        assert result is None


class TestExtractSimpleDecision:
    def test_extract_buy(self, mock_llm):
        sp = SignalProcessor(mock_llm)
        result = sp._extract_simple_decision("建议买入该股票，目标价位：45.50", True)
        assert result["action"] == "买入"
        assert result["target_price"] == 45.50

    def test_extract_sell(self, mock_llm):
        sp = SignalProcessor(mock_llm)
        result = sp._extract_simple_decision("建议SELL卖出该股票", True)
        assert result["action"] == "卖出"

    def test_extract_hold(self, mock_llm):
        sp = SignalProcessor(mock_llm)
        result = sp._extract_simple_decision("建议HOLD持有观望", True)
        assert result["action"] == "持有"

    def test_default_confidence(self, mock_llm):
        sp = SignalProcessor(mock_llm)
        result = sp._extract_simple_decision("市场中性", True)
        assert result["confidence"] == 0.7

    def test_price_from_yuan_pattern(self, mock_llm):
        sp = SignalProcessor(mock_llm)
        result = sp._extract_simple_decision("建议买入，价格88.50元", True)
        assert result["target_price"] == 88.50


class TestGetDefaultDecision:
    def test_returns_correct_structure(self, mock_llm):
        sp = SignalProcessor(mock_llm)
        result = sp._get_default_decision()
        assert result["action"] == "持有"
        assert result["target_price"] is None
        assert result["confidence"] == 0.5
        assert result["risk_score"] == 0.5
        assert "reasoning" in result


class TestProcessSignalFallback:
    def test_llm_exception_falls_back_to_simple(self, mock_llm):
        mock_llm.invoke.side_effect = Exception("LLM error")
        sp = SignalProcessor(mock_llm)
        with patch("app.utils.stock_utils.StockUtils.get_market_info", return_value={
            "is_china": True, "is_hk": False, "currency_name": "人民币",
            "currency_symbol": "¥", "market_name": "A股",
        }):
            result = sp.process_signal("建议买入，目标价位50元", stock_symbol="000001")
        assert result["action"] == "买入"
        assert result["target_price"] == 50.0
