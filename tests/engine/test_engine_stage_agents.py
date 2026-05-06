"""测试 Stage 2/3/4 代理的真实行为（状态转换、消息构建、报告生成）"""

import copy
import json
import pytest
import tempfile
import os
from unittest.mock import MagicMock, patch, mock_open

from app.engine.agents.stage_2.bull_researcher import create_bull_researcher
from app.engine.agents.stage_2.bear_researcher import create_bear_researcher
from app.engine.agents.stage_3.aggresive_debator import create_risky_debator
from app.engine.agents.stage_3.conservative_debator import create_safe_debator
from app.engine.agents.stage_3.neutral_debator import create_neutral_debator
from app.engine.agents.stage_3.risk_manager import create_risk_manager
from app.engine.agents.stage_4.summary_agent import create_summary_agent


def _make_llm_with_response(text):
    llm = MagicMock()
    resp = MagicMock()
    resp.content = text
    llm.invoke.return_value = resp
    return llm


MARKET_INFO_CN = {
    "is_china": True, "is_hk": False, "is_us": False,
    "currency_name": "人民币", "currency_symbol": "¥", "market_name": "A股",
}


def _base_state():
    return {
        "messages": [],
        "company_of_interest": "000001",
        "trade_date": "2024-12-31",
        "task_id": "test-task-001",
        "investment_debate_state": {
            "history": "",
            "current_response": "",
            "count": 0,
            "current_round_index": 0,
            "max_rounds": 2,
            "rounds": [],
            "bull_report_content": "",
            "bear_report_content": "",
            "bull_history": "",
            "bear_history": "",
            "judge_decision": "",
        },
        "risk_debate_state": {
            "history": "",
            "current_risky_response": "",
            "current_safe_response": "",
            "current_neutral_response": "",
            "count": 0,
            "latest_speaker": "",
            "risky_history": "",
            "safe_history": "",
            "neutral_history": "",
            "judge_decision": "",
            "rounds": [],
            "current_round_index": 0,
            "max_rounds": 3,
            "risky_report_content": "",
            "safe_report_content": "",
            "neutral_report_content": "",
        },
        "reports": {
            "market_report": "市场技术指标显示上升趋势",
            "fundamentals_report": "基本面稳健",
        },
        "market_report": "市场技术指标显示上升趋势",
        "fundamentals_report": "基本面稳健",
        "trader_investment_plan": "建议买入100股",
    }


# ===== Bull/Bear 公共 patch 装饰器 =====
# bull_researcher / bear_researcher 内部全部使用延迟导入：
#   - StockUtils: from app.utils.stock_utils import StockUtils
#   - DynamicAnalystFactory: from app.engine.agents.analysts.dynamic_analyst import DynamicAnalystFactory
#   - load_agent_config: from app.engine.agents.utils.generic_agent import load_agent_config
#   - settings: from app.core.config import settings
# 因此必须 patch 源模块路径

def _bull_bear_patches():
    """返回 bull/bear 研究员测试所需的公共 patch 列表"""
    return [
        patch("app.engine.agents.analysts.dynamic_analyst.DynamicAnalystFactory.get_all_agents", return_value=[]),
        patch("app.utils.stock_utils.StockUtils.get_market_info", return_value=MARKET_INFO_CN),
        patch("app.engine.agents.utils.generic_agent.load_agent_config", return_value="你是看涨研究员"),
        patch("app.data.interface.get_china_stock_info_unified", return_value="股票名称:平安银行\n股票代码:000001"),
        patch("app.data.data_source_manager.get_china_stock_info_unified", return_value={"name": "平安银行"}),
        patch("app.core.config.settings"),
    ]


# ===== Stage 2: Bull Researcher =====

class TestBullResearcherBehavior:
    def test_returns_investment_debate_state(self):
        patches = _bull_bear_patches()
        with patches[0] as mock_factory, patches[1] as mock_market, \
             patches[2] as mock_config, patches[3] as mock_stock_info, \
             patches[4] as mock_stock_info2, patches[5] as mock_settings:
            mock_settings.runtime_dir = tempfile.mkdtemp()
            llm = _make_llm_with_response("看涨观点：市场前景乐观")
            memory = MagicMock()
            node = create_bull_researcher(llm, memory)
            result = node(_base_state())

            assert "investment_debate_state" in result
            ids = result["investment_debate_state"]
            assert ids["bull_history"] != ""
            assert "乐观" in ids["bull_history"]
            assert ids["count"] == 1
            assert ids["latest_speaker"] == "Bull Researcher"
            assert ids["current_round_index"] == 0  # (0+1)//2 = 0

    def test_returns_reports(self):
        patches = _bull_bear_patches()
        with patches[0] as mock_factory, patches[1] as mock_market, \
             patches[2] as mock_config, patches[3] as mock_stock_info, \
             patches[4] as mock_stock_info2, patches[5] as mock_settings:
            mock_settings.runtime_dir = tempfile.mkdtemp()
            llm = _make_llm_with_response("看涨分析报告内容")
            memory = MagicMock()
            node = create_bull_researcher(llm, memory)
            result = node(_base_state())

            assert "reports" in result
            assert "bull_researcher" in result["reports"]
            assert "看涨分析报告内容" in result["reports"]["bull_researcher"]

    def test_debate_history_contains_bull_argument(self):
        patches = _bull_bear_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5] as mock_settings:
            mock_settings.runtime_dir = tempfile.mkdtemp()
            llm = _make_llm_with_response("强烈看好后市走势")
            memory = MagicMock()
            node = create_bull_researcher(llm, memory)
            result = node(_base_state())

            ids = result["investment_debate_state"]
            assert "强烈看好后市走势" in ids["current_response"]
            assert ids["history"] != ""

    def test_injects_stage1_reports_into_llm_messages(self):
        patches = _bull_bear_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5] as mock_settings:
            mock_settings.runtime_dir = tempfile.mkdtemp()
            llm = _make_llm_with_response("分析完成")
            memory = MagicMock()
            node = create_bull_researcher(llm, memory)
            state = _base_state()
            state["news_report"] = "新闻利好"
            result = node(state)

            # 验证 LLM 被调用
            assert llm.invoke.called
            call_args = llm.invoke.call_args
            messages = call_args[0][0]
            # 应该包含 system + report messages + trigger
            msg_contents = [m.content for m in messages]
            assert any("市场技术指标" in c for c in msg_contents)
            assert any("基本面稳健" in c for c in msg_contents)
            assert any("新闻利好" in c for c in msg_contents)


# ===== Stage 2: Bear Researcher =====

class TestBearResearcherBehavior:
    def test_returns_bear_history(self):
        patches = _bull_bear_patches()
        with patches[0], patches[1], patches[2] as mock_config, \
             patches[3], patches[4], patches[5] as mock_settings:
            mock_config.return_value = "你是看跌研究员"
            mock_settings.runtime_dir = tempfile.mkdtemp()
            llm = _make_llm_with_response("看跌观点：市场风险较大")
            memory = MagicMock()
            node = create_bear_researcher(llm, memory)
            result = node(_base_state())

            ids = result["investment_debate_state"]
            assert ids["bear_history"] != ""
            assert "风险" in ids["bear_history"]
            assert ids["count"] == 1

    def test_returns_bear_reports(self):
        patches = _bull_bear_patches()
        with patches[0], patches[1], patches[2] as mock_config, \
             patches[3], patches[4], patches[5] as mock_settings:
            mock_config.return_value = "你是看跌研究员"
            mock_settings.runtime_dir = tempfile.mkdtemp()
            llm = _make_llm_with_response("风险警示报告")
            memory = MagicMock()
            node = create_bear_researcher(llm, memory)
            result = node(_base_state())

            assert "reports" in result
            assert "bear_researcher" in result["reports"]
            assert "风险警示报告" in result["reports"]["bear_researcher"]

    def test_bear_preserves_bull_history(self):
        patches = _bull_bear_patches()
        with patches[0], patches[1], patches[2] as mock_config, \
             patches[3], patches[4], patches[5] as mock_settings:
            mock_config.return_value = "你是看跌研究员"
            mock_settings.runtime_dir = tempfile.mkdtemp()
            state = _base_state()
            state["investment_debate_state"]["bull_history"] = "已有看涨观点"
            llm = _make_llm_with_response("看跌分析")
            memory = MagicMock()
            node = create_bear_researcher(llm, memory)
            result = node(state)

            ids = result["investment_debate_state"]
            assert ids["bull_history"] == "已有看涨观点"


# ===== Stage 3 公共 patch =====
# Stage 3 的 aggresive/conservative/neutral_debator 和 risk_manager 使用模块级导入：
#   from app.engine.agents.utils.generic_agent import resolve_company_name, load_agent_config, build_stage3_report_path
# StockUtils 仍然是延迟导入

def _stage3_debator_patches(module_name):
    """返回 Stage 3 debator 测试所需的 patch 列表"""
    return [
        patch(f"{module_name}.resolve_company_name", return_value="平安银行"),
        patch(f"{module_name}.load_agent_config", return_value="你是分析师"),
        patch("app.utils.stock_utils.StockUtils.get_market_info", return_value=MARKET_INFO_CN),
        patch(f"{module_name}.build_stage3_report_path"),
    ]


# ===== Stage 3: Risky Debator =====

class TestRiskyDebatorBehavior:
    def test_updates_risk_debate_state(self):
        module = "app.engine.agents.stage_3.aggresive_debator"
        with patch(f"{module}.resolve_company_name", return_value="平安银行"), \
             patch(f"{module}.load_agent_config", return_value="你是激进分析师"), \
             patch("app.utils.stock_utils.StockUtils.get_market_info", return_value=MARKET_INFO_CN), \
             patch(f"{module}.build_stage3_report_path") as mock_path:
            mock_path.return_value = os.path.join(tempfile.gettempdir(), "test_risky.md")
            llm = _make_llm_with_response("激进观点：高风险高回报")
            node = create_risky_debator(llm)
            result = node(_base_state())

            rds = result["risk_debate_state"]
            assert rds["risky_history"] != ""
            assert rds["current_risky_response"] != ""
            assert "激进" in rds["risky_history"]
            assert rds["latest_speaker"] == "Risky Analyst"

    def test_increments_count(self):
        module = "app.engine.agents.stage_3.aggresive_debator"
        with patch(f"{module}.resolve_company_name", return_value="平安银行"), \
             patch(f"{module}.load_agent_config", return_value="你是激进分析师"), \
             patch("app.utils.stock_utils.StockUtils.get_market_info", return_value=MARKET_INFO_CN), \
             patch(f"{module}.build_stage3_report_path") as mock_path:
            mock_path.return_value = os.path.join(tempfile.gettempdir(), "test_risky.md")
            llm = _make_llm_with_response("激进观点")
            node = create_risky_debator(llm)
            result = node(_base_state())

            assert result["risk_debate_state"]["count"] == 1

    def test_returns_reports(self):
        module = "app.engine.agents.stage_3.aggresive_debator"
        with patch(f"{module}.resolve_company_name", return_value="平安银行"), \
             patch(f"{module}.load_agent_config", return_value="你是激进分析师"), \
             patch("app.utils.stock_utils.StockUtils.get_market_info", return_value=MARKET_INFO_CN), \
             patch(f"{module}.build_stage3_report_path") as mock_path:
            mock_path.return_value = os.path.join(tempfile.gettempdir(), "test_risky.md")
            llm = _make_llm_with_response("激进报告内容")
            node = create_risky_debator(llm)
            result = node(_base_state())

            assert "reports" in result
            assert "risky_analyst" in result["reports"]
            assert "激进报告内容" in result["reports"]["risky_analyst"]

    def test_accumulates_report_content_across_rounds(self):
        module = "app.engine.agents.stage_3.aggresive_debator"
        with patch(f"{module}.resolve_company_name", return_value="平安银行"), \
             patch(f"{module}.load_agent_config", return_value="你是激进分析师"), \
             patch("app.utils.stock_utils.StockUtils.get_market_info", return_value=MARKET_INFO_CN), \
             patch(f"{module}.build_stage3_report_path") as mock_path:
            mock_path.return_value = os.path.join(tempfile.gettempdir(), "test_risky.md")
            state = _base_state()
            state["risk_debate_state"]["risky_report_content"] = "## 初始观点：激进策略\n\n第一轮内容"
            state["risk_debate_state"]["current_round_index"] = 1
            # 必须预填充 round 0 的数据，否则 rounds[1] 会越界
            state["risk_debate_state"]["rounds"] = [{"risky": "第一轮内容"}]

            llm = _make_llm_with_response("第二轮激进观点")
            node = create_risky_debator(llm)
            result = node(state)

            report = result["risk_debate_state"]["risky_report_content"]
            assert "第一轮内容" in report
            assert "第二轮激进观点" in report


# ===== Stage 3: Safe Debator =====

class TestSafeDebatorBehavior:
    def test_updates_safe_history(self):
        module = "app.engine.agents.stage_3.conservative_debator"
        with patch(f"{module}.resolve_company_name", return_value="平安银行"), \
             patch(f"{module}.load_agent_config", return_value="你是保守分析师"), \
             patch("app.utils.stock_utils.StockUtils.get_market_info", return_value=MARKET_INFO_CN), \
             patch(f"{module}.build_stage3_report_path") as mock_path:
            mock_path.return_value = os.path.join(tempfile.gettempdir(), "test_safe.md")
            llm = _make_llm_with_response("保守观点：风险需控制")
            node = create_safe_debator(llm)
            result = node(_base_state())

            rds = result["risk_debate_state"]
            assert rds["safe_history"] != ""
            assert "风险" in rds["safe_history"]

    def test_safe_report_content(self):
        module = "app.engine.agents.stage_3.conservative_debator"
        with patch(f"{module}.resolve_company_name", return_value="平安银行"), \
             patch(f"{module}.load_agent_config", return_value="你是保守分析师"), \
             patch("app.utils.stock_utils.StockUtils.get_market_info", return_value=MARKET_INFO_CN), \
             patch(f"{module}.build_stage3_report_path") as mock_path:
            mock_path.return_value = os.path.join(tempfile.gettempdir(), "test_safe.md")
            llm = _make_llm_with_response("保守策略分析报告")
            node = create_safe_debator(llm)
            result = node(_base_state())

            assert "reports" in result
            assert "safe_analyst" in result["reports"]


# ===== Stage 3: Neutral Debator =====

class TestNeutralDebatorBehavior:
    def test_updates_neutral_history(self):
        module = "app.engine.agents.stage_3.neutral_debator"
        with patch(f"{module}.resolve_company_name", return_value="平安银行"), \
             patch(f"{module}.load_agent_config", return_value="你是中性分析师"), \
             patch("app.utils.stock_utils.StockUtils.get_market_info", return_value=MARKET_INFO_CN), \
             patch(f"{module}.build_stage3_report_path") as mock_path:
            mock_path.return_value = os.path.join(tempfile.gettempdir(), "test_neutral.md")
            llm = _make_llm_with_response("中性观点：观望为主")
            node = create_neutral_debator(llm)
            result = node(_base_state())

            rds = result["risk_debate_state"]
            assert rds["neutral_history"] != ""
            assert "观望" in rds["neutral_history"]

    def test_neutral_report_in_reports(self):
        module = "app.engine.agents.stage_3.neutral_debator"
        with patch(f"{module}.resolve_company_name", return_value="平安银行"), \
             patch(f"{module}.load_agent_config", return_value="你是中性分析师"), \
             patch("app.utils.stock_utils.StockUtils.get_market_info", return_value=MARKET_INFO_CN), \
             patch(f"{module}.build_stage3_report_path") as mock_path:
            mock_path.return_value = os.path.join(tempfile.gettempdir(), "test_neutral.md")
            llm = _make_llm_with_response("中性平衡分析")
            node = create_neutral_debator(llm)
            result = node(_base_state())

            assert "reports" in result
            assert "neutral_analyst" in result["reports"]


# ===== Stage 3: Risk Manager =====

class TestRiskManagerBehavior:

    def test_sets_final_trade_decision(self):
        module = "app.engine.agents.stage_3.risk_manager"
        with patch(f"{module}.resolve_company_name", return_value="平安银行"), \
             patch(f"{module}.load_agent_config", return_value="你是首席风控官"), \
             patch("app.utils.stock_utils.StockUtils.get_market_info", return_value=MARKET_INFO_CN), \
             patch(f"{module}.build_stage3_report_path") as mock_path:
            mock_path.return_value = os.path.join(tempfile.gettempdir(), "test_rm.md")
            llm = _make_llm_with_response("最终风控裁决：建议持有")
            memory = MagicMock()
            node = create_risk_manager(llm, memory)
            result = node(_base_state())

            assert "final_trade_decision" in result
            assert "持有" in result["final_trade_decision"]

    def test_sets_judge_decision(self):
        module = "app.engine.agents.stage_3.risk_manager"
        with patch(f"{module}.resolve_company_name", return_value="平安银行"), \
             patch(f"{module}.load_agent_config", return_value="你是首席风控官"), \
             patch("app.utils.stock_utils.StockUtils.get_market_info", return_value=MARKET_INFO_CN), \
             patch(f"{module}.build_stage3_report_path") as mock_path:
            mock_path.return_value = os.path.join(tempfile.gettempdir(), "test_rm.md")
            llm = _make_llm_with_response("风控裁决报告")
            memory = MagicMock()
            node = create_risk_manager(llm, memory)
            result = node(_base_state())

            rds = result["risk_debate_state"]
            assert rds["judge_decision"] == "风控裁决报告"

    def test_preserves_original_state(self):
        module = "app.engine.agents.stage_3.risk_manager"
        with patch(f"{module}.resolve_company_name", return_value="平安银行"), \
             patch(f"{module}.load_agent_config", return_value="你是首席风控官"), \
             patch("app.utils.stock_utils.StockUtils.get_market_info", return_value=MARKET_INFO_CN), \
             patch(f"{module}.build_stage3_report_path") as mock_path:
            mock_path.return_value = os.path.join(tempfile.gettempdir(), "test_rm.md")
            llm = _make_llm_with_response("裁决")
            memory = MagicMock()
            node = create_risk_manager(llm, memory)
            original_state = _base_state()
            original_state["risk_debate_state"]["risky_history"] = "历史激进"
            original_state["risk_debate_state"]["safe_history"] = "历史保守"
            original_state["risk_debate_state"]["count"] = 6
            result = node(original_state)

            assert result["risk_debate_state"]["count"] == 6
            assert result["risk_debate_state"]["risky_history"] == "历史激进"
            assert result["risk_debate_state"]["safe_history"] == "历史保守"

    def test_reports_include_risk_manager_decision(self):
        module = "app.engine.agents.stage_3.risk_manager"
        with patch(f"{module}.resolve_company_name", return_value="平安银行"), \
             patch(f"{module}.load_agent_config", return_value="你是首席风控官"), \
             patch("app.utils.stock_utils.StockUtils.get_market_info", return_value=MARKET_INFO_CN), \
             patch(f"{module}.build_stage3_report_path") as mock_path:
            mock_path.return_value = os.path.join(tempfile.gettempdir(), "test_rm.md")
            llm = _make_llm_with_response("风控决策：谨慎持有")
            memory = MagicMock()
            node = create_risk_manager(llm, memory)
            result = node(_base_state())

            assert "reports" in result
            assert "risk_manager_decision" in result["reports"]
            assert "谨慎持有" in result["reports"]["risk_manager_decision"]


# ===== Stage 4: Summary Agent =====

class TestSummaryAgentBehavior:
    def test_collects_all_report_fields(self):
        llm = _make_llm_with_response(json.dumps({
            "key_indicators": {"entry_price": "12.5", "target_price": "15", "stop_loss": "11"},
            "model_confidence": 75,
            "risk_assessment": {"level": "Medium", "score": 5.0, "description": "中等风险"},
            "analysis_summary": "综合分析",
            "investment_recommendation": "建议买入",
            "analysis_reference": [],
            "final_signal": "Buy",
        }))
        node = create_summary_agent(llm)
        state = {
            "company_of_interest": "000001",
            "market_report": "市场报告",
            "news_report": "新闻报告",
            "fundamentals_report": "基本面报告",
            "trader_investment_plan": "买入计划",
            "risk_debate_state": {"history": "辩论历史"},
            "reports": {},
        }
        result = node(state)
        assert "structured_summary" in result
        assert result["structured_summary"]["model_confidence"] == 75
        assert result["structured_summary"]["final_signal"] == "Buy"

    def test_handles_json_decode_error(self):
        llm = _make_llm_with_response("not valid json")
        node = create_summary_agent(llm)
        state = {"company_of_interest": "000001", "risk_debate_state": {}}
        result = node(state)
        assert "structured_summary" in result
        assert result["structured_summary"]["model_confidence"] == 50
        assert result["structured_summary"]["final_signal"] == "Hold"

    def test_handles_llm_exception(self):
        llm = MagicMock()
        llm.invoke.side_effect = Exception("LLM error")
        node = create_summary_agent(llm)
        state = {"company_of_interest": "000001", "risk_debate_state": {}}
        result = node(state)
        assert "structured_summary" in result
        assert result["structured_summary"]["model_confidence"] == 0

    def test_cleans_markdown_json(self):
        llm = _make_llm_with_response('```json\n{"key_indicators": {}, "model_confidence": 80, "risk_assessment": {"level": "Low", "score": 3.0, "description": "低风险"}, "analysis_summary": "测试", "investment_recommendation": "持有", "analysis_reference": [], "final_signal": "Hold"}\n```')
        node = create_summary_agent(llm)
        state = {"company_of_interest": "000001", "risk_debate_state": {}}
        result = node(state)
        assert result["structured_summary"]["model_confidence"] == 80

    def test_empty_state_defaults(self):
        llm = _make_llm_with_response(json.dumps({
            "key_indicators": {"entry_price": "N/A", "target_price": "N/A", "stop_loss": "N/A"},
            "model_confidence": 0,
            "risk_assessment": {"level": "Low", "score": 0.0, "description": "无数据"},
            "analysis_summary": "数据获取失败",
            "investment_recommendation": "无建议",
            "analysis_reference": [],
            "final_signal": "Hold",
        }))
        node = create_summary_agent(llm)
        state = {"company_of_interest": "Unknown", "risk_debate_state": {}}
        result = node(state)
        assert result["structured_summary"]["model_confidence"] == 0

    def test_llm_receives_all_reports(self):
        llm = _make_llm_with_response(json.dumps({
            "key_indicators": {}, "model_confidence": 60,
            "risk_assessment": {"level": "Medium", "score": 5.0, "description": "test"},
            "analysis_summary": "test", "investment_recommendation": "test",
            "analysis_reference": [], "final_signal": "Hold",
        }))
        node = create_summary_agent(llm)
        state = {
            "company_of_interest": "000001",
            "market_report": "市场分析详情",
            "news_report": "新闻摘要",
            "trader_investment_plan": "交易计划",
            "final_trade_decision": "最终决策",
            "risk_debate_state": {"history": "辩论记录"},
            "sentiment_report": "情绪报告",
            "custom_report": "自定义报告内容",
        }
        result = node(state)

        # 验证 LLM 收到的 prompt 包含各报告
        call_args = llm.invoke.call_args
        messages = call_args[0][0]
        system_content = messages[0].content
        assert "市场分析详情" in system_content
        assert "交易计划" in system_content
        assert "最终决策" in system_content
        assert "自定义报告内容" in system_content
