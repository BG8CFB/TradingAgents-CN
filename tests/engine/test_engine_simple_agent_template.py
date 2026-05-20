"""
测试 SimpleAgentTemplate 代理模板

业务逻辑测试：format_tool_result、_INJECT_TOOL_ARGS_MAP 数据验证
LLM 集成测试：标记 @pytest.mark.ai，使用真实 API 测试 agent 节点执行
"""

import json
import pytest
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from app.engine.agents.analysts.simple_agent_template import (
    format_tool_result,
    _inject_tool_data,
    _INJECT_TOOL_ARGS_MAP,
    create_simple_agent,
)


class TestFormatToolResult:
    """format_tool_result 纯逻辑测试"""

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
    """工具参数映射数据验证"""

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
    """_inject_tool_data 数据注入逻辑"""

    def test_skips_tools_not_in_map(self):
        """不在映射表中的工具不触发注入"""

        class FakeTool:
            name = "unknown_tool"

        messages = []
        _inject_tool_data(
            "test", [FakeTool()],
            {"ticker": "000001", "trade_date": "2024-12-31"},
            messages,
        )
        assert len(messages) == 0

    def test_skips_when_ticker_empty_and_needed(self):
        """ticker 为空且工具需要 ticker 时不注入数据（但可能有 SystemMessage 前导说明）"""

        class FakeTool:
            name = "get_stock_data"

        messages = []
        _inject_tool_data(
            "test", [FakeTool()],
            {"ticker": "", "trade_date": "2024-12-31"},
            messages,
        )
        # 工具因缺少 ticker 跳过，不应有 AIMessage + ToolMessage 对
        assert not any(isinstance(m, AIMessage) for m in messages)
        assert not any(isinstance(m, ToolMessage) for m in messages)

    def test_injects_tool_result_into_messages(self):
        """get_finance_news 不需要 ticker，应成功注入数据"""

        class FakeTool:
            name = "get_finance_news"

            def invoke(self, args):
                return {"news": "今日要闻"}

        messages = []
        _inject_tool_data(
            "test", [FakeTool()],
            {"ticker": "", "trade_date": "2024-12-31"},
            messages,
        )
        # SystemMessage 前导说明 + AIMessage + ToolMessage
        assert any(isinstance(m, SystemMessage) for m in messages)
        assert any(isinstance(m, AIMessage) for m in messages)
        assert any(isinstance(m, ToolMessage) for m in messages)

    def test_handles_tool_exception_gracefully(self):
        """工具执行异常时不崩溃"""

        class FailingTool:
            name = "get_finance_news"

            def invoke(self, args):
                raise RuntimeError("外部服务不可用")

        messages = []
        _inject_tool_data(
            "test", [FailingTool()],
            {"ticker": "", "trade_date": "2024-12-31"},
            messages,
        )
        # 工具执行失败，不应有 AIMessage + ToolMessage 对（可能有 SystemMessage）
        assert not any(isinstance(m, AIMessage) for m in messages)
        assert not any(isinstance(m, ToolMessage) for m in messages)


class TestCreateSimpleAgentCallable:
    """create_simple_agent 工厂函数基本验证"""

    def test_returns_callable(self):
        node_fn = create_simple_agent(
            name="测试分析师", slug="test-analyst", llm=None,
            tools=[], system_prompt="你是测试分析师",
        )
        assert callable(node_fn)

    def test_returns_callable_with_tools(self):
        node_fn = create_simple_agent(
            name="测试", slug="test", llm=None,
            tools=[], system_prompt="测试",
        )
        assert callable(node_fn)


class TestSimpleAgentWithRealLLM:
    """使用真实 LLM 的 agent 执行测试"""

    @pytest.mark.ai
    def test_agent_executes_with_real_llm(self):
        """使用真实 LLM 执行 agent 节点"""
        from app.engine.llm_adapters.factory import create_llm
        import os

        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            pytest.skip("需要 DEEPSEEK_API_KEY 环境变量")

        llm = create_llm(provider="deepseek", model="deepseek-chat", api_key=api_key)
        node = create_simple_agent(
            name="市场分析师", slug="market-analyst", llm=llm,
            tools=[], system_prompt="你是市场分析师，请简要分析。",
        )
        state = {
            "messages": [],
            "company_of_interest": "000001",
            "trade_date": "2024-12-31",
            "task_id": None,
            "reports": {},
        }
        result = node(state)
        assert "market_report" in result
        assert isinstance(result["market_report"], str)
        assert len(result["market_report"]) > 0
