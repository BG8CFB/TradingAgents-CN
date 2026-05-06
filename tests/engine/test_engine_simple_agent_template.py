"""测试 SimpleAgentTemplate 代理模板：覆盖 format_tool_result、_inject_tool_data、create_simple_agent 节点执行"""

import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.engine.agents.analysts.simple_agent_template import (
    format_tool_result,
    _inject_tool_data,
    _INJECT_TOOL_ARGS_MAP,
    create_simple_agent,
)


class TestFormatToolResult:
    def test_none_returns_empty_string(self):
        assert format_tool_result(None) == ""

    def test_dict_returns_json(self):
        data = {"key": "value", "num": 42}
        result = format_tool_result(data)
        parsed = json.loads(result)
        assert parsed == data

    def test_list_returns_json(self):
        data = [1, 2, 3]
        result = format_tool_result(data)
        parsed = json.loads(result)
        assert parsed == data

    def test_string_passthrough(self):
        assert format_tool_result("hello") == "hello"

    def test_int_to_string(self):
        assert format_tool_result(42) == "42"

    def test_float_to_string(self):
        assert format_tool_result(3.14) == "3.14"

    def test_empty_dict_returns_json(self):
        result = format_tool_result({})
        assert result == "{}"

    def test_empty_list_returns_json(self):
        result = format_tool_result([])
        assert result == "[]"

    def test_nested_dict(self):
        data = {"a": {"b": [1, 2]}}
        result = format_tool_result(data)
        parsed = json.loads(result)
        assert parsed["a"]["b"] == [1, 2]

    def test_chinese_content(self):
        data = {"名称": "平安银行", "价格": 12.5}
        result = format_tool_result(data)
        assert "平安银行" in result


class TestInjectToolArgsMap:
    def test_expected_tool_names_present(self):
        expected = [
            "get_stock_data", "get_stock_news", "get_stock_fundamentals",
            "get_stock_sentiment", "get_china_market_overview", "get_finance_news",
        ]
        for name in expected:
            assert name in _INJECT_TOOL_ARGS_MAP, f"缺少工具映射: {name}"

    def test_map_values_are_dicts(self):
        for tool_name, args_map in _INJECT_TOOL_ARGS_MAP.items():
            assert isinstance(args_map, dict), f"{tool_name} 的映射不是字典"


class TestInjectToolData:
    def test_skips_tools_not_in_map(self):
        tool = MagicMock()
        tool.name = "unknown_tool"
        messages = []
        _inject_tool_data("test", [tool], {"ticker": "000001", "trade_date": "2024-12-31"}, messages)
        assert len(messages) == 0

    def test_skips_when_ticker_empty_and_needed(self):
        tool = MagicMock()
        tool.name = "get_stock_data"
        messages = []
        _inject_tool_data("test", [tool], {"ticker": "", "trade_date": "2024-12-31"}, messages)
        assert len(messages) == 0

    @patch("app.engine.agents.analysts.simple_agent_template.format_tool_result", return_value="data")
    def test_injects_tool_result_into_messages(self, mock_format):
        tool = MagicMock()
        tool.name = "get_finance_news"
        tool.invoke.return_value = {"news": "headline"}
        messages = []
        _inject_tool_data("test", [tool], {"ticker": "", "trade_date": "2024-12-31"}, messages)
        assert len(messages) == 2
        assert isinstance(messages[0], AIMessage)
        assert isinstance(messages[1], ToolMessage)

    @patch("app.engine.agents.analysts.simple_agent_template.format_tool_result", return_value="data")
    def test_handles_tool_exception_gracefully(self, mock_format):
        tool = MagicMock()
        tool.name = "get_finance_news"
        tool.invoke.side_effect = Exception("tool error")
        messages = []
        _inject_tool_data("test", [tool], {"ticker": "", "trade_date": "2024-12-31"}, messages)
        assert len(messages) == 0


# ===== 节点执行测试 =====

def _make_llm_no_tool_call(response_text="分析报告内容"):
    """创建一个 LLM mock：不触发工具调用，直接返回文本"""
    llm = MagicMock()
    resp = MagicMock()
    resp.content = response_text
    resp.tool_calls = []
    llm.invoke.return_value = resp
    llm.bind_tools.return_value = llm
    return llm


def _make_llm_with_tool_call_then_final(tool_name="get_stock_data", tool_args=None, final_text="最终分析报告"):
    """创建一个 LLM mock：第一次返回工具调用，第二次返回最终文本"""
    llm = MagicMock()
    # 第一次调用：返回工具调用
    tool_resp = MagicMock()
    tool_resp.content = ""
    tool_resp.tool_calls = [{
        "name": tool_name,
        "args": tool_args or {"stock_code": "000001"},
        "id": "call_123",
    }]
    # 第二次调用：返回最终报告
    final_resp = MagicMock()
    final_resp.content = final_text
    final_resp.tool_calls = []

    llm.invoke.side_effect = [tool_resp, final_resp]
    llm.bind_tools.return_value = llm
    return llm


def _base_state():
    return {
        "messages": [],
        "company_of_interest": "000001",
        "trade_date": "2024-12-31",
        "task_id": "test-task-001",
        "reports": {},
    }


# 公共 mock 路径（simple_agent_template 内部全部延迟导入）
_COMMON_PATCHES = [
    "app.utils.stock_utils.StockUtils.get_market_info",
    "app.data.interface.get_china_stock_info_unified",
    "app.engine.agents.analysts.dynamic_analyst.ProgressManager",
    "app.engine.agents.analysts.simple_agent_factory.SimpleAgentFactory._get_analyst_icon",
]


class TestCreateSimpleAgentNodeExecution:
    """测试 create_simple_agent 返回的节点函数的实际执行行为"""

    def _patches(self):
        return (
            patch("app.utils.stock_utils.StockUtils.get_market_info", return_value={
                "is_china": True, "is_hk": False, "is_us": False,
                "currency_name": "人民币", "currency_symbol": "¥", "market_name": "A股",
            }),
            patch("app.data.interface.get_china_stock_info_unified", return_value="股票名称:平安银行\n股票代码:000001"),
            patch("app.engine.agents.analysts.dynamic_analyst.ProgressManager"),
            patch("app.engine.agents.analysts.simple_agent_factory.SimpleAgentFactory._get_analyst_icon", return_value="📊"),
            patch("app.engine.agents.analysts.simple_agent_template._RATE_LIMITER_AVAILABLE", False),
        )

    def _apply_patches(self):
        """以 context manager 方式应用所有 patch，返回退出函数"""
        patches = self._patches()
        entered = []
        for p in patches:
            cm = p.__enter__()
            entered.append(cm)
        def exit_all():
            for p in reversed(patches):
                p.__exit__(None, None, None)
        return entered, exit_all

    def test_no_tool_call_returns_report(self):
        """LLM 不调用工具，直接返回报告"""
        _, exit_all = self._apply_patches()
        try:
            llm = _make_llm_no_tool_call("市场趋势向上，建议持有")
            node = create_simple_agent(
                name="市场分析师", slug="market-analyst", llm=llm,
                tools=[], system_prompt="你是市场分析师",
            )
            result = node(_base_state())

            assert "market_report" in result
            assert result["market_report"] == "市场趋势向上，建议持有"
            assert "reports" in result
            assert "market_report" in result["reports"]
            assert len(result["messages"]) == 1
            assert isinstance(result["messages"][0], AIMessage)
        finally:
            exit_all()

    def test_tool_call_executed_and_loop_continues(self):
        """LLM 调用工具后继续循环，最终返回报告"""
        _, exit_all = self._apply_patches()
        try:
            tool = MagicMock()
            tool.name = "get_stock_data"
            tool.invoke.return_value = {"price": 12.5}

            llm = _make_llm_with_tool_call_then_final(
                tool_name="get_stock_data",
                final_text="基于数据的分析报告",
            )
            node = create_simple_agent(
                name="市场分析师", slug="market-analyst", llm=llm,
                tools=[tool], system_prompt="你是市场分析师",
            )
            result = node(_base_state())

            assert result["market_report"] == "基于数据的分析报告"
            assert tool.invoke.called
        finally:
            exit_all()

    def test_report_key_derived_from_slug(self):
        """验证 report_key 由 slug 正确生成"""
        _, exit_all = self._apply_patches()
        try:
            llm = _make_llm_no_tool_call("报告")
            node = create_simple_agent(
                name="新闻分析师", slug="news-analyst", llm=llm,
                tools=[], system_prompt="你是新闻分析师",
            )
            result = node(_base_state())

            assert "news_report" in result
        finally:
            exit_all()

    def test_preserves_original_state_fields(self):
        """验证返回值保留了原始 state 中的字段"""
        _, exit_all = self._apply_patches()
        try:
            llm = _make_llm_no_tool_call("报告")
            state = _base_state()
            state["custom_field"] = "自定义值"
            node = create_simple_agent(
                name="测试", slug="test-analyst", llm=llm,
                tools=[], system_prompt="你是测试分析师",
            )
            result = node(state)

            assert result["custom_field"] == "自定义值"
            assert result["company_of_interest"] == "000001"
        finally:
            exit_all()

    def test_state_system_prompt_contains_context(self):
        """验证 LLM 收到的 system prompt 包含股票上下文"""
        _, exit_all = self._apply_patches()
        try:
            llm = _make_llm_no_tool_call("报告")
            node = create_simple_agent(
                name="测试", slug="test-analyst", llm=llm,
                tools=[], system_prompt="你是测试分析师",
            )
            node(_base_state())

            assert llm.invoke.called
            call_args = llm.invoke.call_args
            messages = call_args[0][0]
            system_msg = messages[0]
            assert isinstance(system_msg, SystemMessage)
            assert "000001" in system_msg.content
            assert "平安银行" in system_msg.content
            assert "2024-12-31" in system_msg.content
            assert "你是测试分析师" in system_msg.content
        finally:
            exit_all()

    def test_tool_not_found_still_continues(self):
        """当工具未在 tools 列表中找到时，继续执行循环"""
        _, exit_all = self._apply_patches()
        try:
            llm = _make_llm_with_tool_call_then_final(
                tool_name="nonexistent_tool",
                final_text="即使工具不存在也能完成报告",
            )
            node = create_simple_agent(
                name="测试", slug="test-analyst", llm=llm,
                tools=[], system_prompt="你是测试分析师",
            )
            result = node(_base_state())

            assert result["test_report"] == "即使工具不存在也能完成报告"
        finally:
            exit_all()

    def test_llm_error_returns_error_report(self):
        """LLM 调用失败时返回错误报告"""
        _, exit_all = self._apply_patches()
        try:
            llm = MagicMock()
            llm.invoke.side_effect = Exception("LLM 服务不可用")
            llm.bind_tools.return_value = llm

            node = create_simple_agent(
                name="测试", slug="test-analyst", llm=llm,
                tools=[], system_prompt="你是测试分析师",
            )
            result = node(_base_state())

            assert "test_report" in result
            assert "分析失败" in result["test_report"]
        finally:
            exit_all()

    def test_inject_tools_preloads_data(self):
        """验证 inject_tools 参数触发数据预加载"""
        _, exit_all = self._apply_patches()
        try:
            inject_tool = MagicMock()
            inject_tool.name = "get_finance_news"
            inject_tool.invoke.return_value = {"news": "今日要闻"}

            llm = _make_llm_no_tool_call("综合报告")
            node = create_simple_agent(
                name="新闻分析师", slug="news-analyst", llm=llm,
                tools=[], system_prompt="你是新闻分析师",
                inject_tools=[inject_tool],
            )
            result = node(_base_state())

            assert inject_tool.invoke.called
            call_args = llm.invoke.call_args
            messages = call_args[0][0]
            assert len(messages) >= 4
        finally:
            exit_all()


class TestCreateSimpleAgentCallable:
    def test_returns_callable(self, mock_llm):
        node_fn = create_simple_agent(
            name="测试分析师", slug="test-analyst", llm=mock_llm,
            tools=[], system_prompt="你是测试分析师",
        )
        assert callable(node_fn)

    def test_node_function_name(self, mock_llm):
        node_fn = create_simple_agent(
            name="测试分析师", slug="test-analyst", llm=mock_llm,
            tools=[], system_prompt="你是测试分析师",
        )
        assert hasattr(node_fn, '__name__') or callable(node_fn)
