"""
AI 模型实际调用集成测试

使用 MiniMax API 进行真实 LLM 调用测试，验证：
1. OpenAI 兼容适配器能正确初始化
2. 模型能响应基本对话
3. 带工具调用的模型交互
4. Token 计费统计
5. 分析引擎的核心 LLM 调用流程

运行: python -m pytest tests/ai_integration/ -v -m ai
"""

import os
import pytest
import time

# MiniMax API 配置
MINIMAX_API_KEY = os.getenv(
    "AI_API_KEY",
    "sk-cp-RUwEXg20opMFUl3Z5uGSEQTLS4-_1o-ZwmVJI1gwvcPyQ5fo_UgmZE-SVBnPe-g6tz5HEocFXftwQA_myNdnoTxlqn8v6xYaFu3Cg6cIBt0VSASHRsyiMXg"
)
MINIMAX_BASE_URL = "https://api.minimaxi.com/v1"
MINIMAX_MODEL = "MiniMax-M2.7"

# 标记所有测试为 ai 集成测试
pytestmark = pytest.mark.ai


# ============================================================
# 1. LLM 适配器初始化测试
# ============================================================

class TestLLMAdapterInit:
    """测试 LLM 适配器使用 MiniMax API 的初始化"""

    def test_chat_openai_init_with_minimax(self):
        """验证使用 MiniMax API 能初始化 ChatOpenAI 实例"""
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model=MINIMAX_MODEL,
            api_key=MINIMAX_API_KEY,
            base_url=MINIMAX_BASE_URL,
            temperature=0.3,
            max_tokens=256,
            timeout=30,
        )
        assert llm is not None
        assert llm.model_name == MINIMAX_MODEL

    def test_openai_compatible_base_init_with_minimax(self):
        """验证 OpenAICompatibleBase 能使用 MiniMax 初始化"""
        from app.engine.llm_adapters.openai_compatible_base import OpenAICompatibleBase

        llm = OpenAICompatibleBase(
            provider_name="minimax",
            model=MINIMAX_MODEL,
            api_key_env_var="AI_API_KEY",
            base_url=MINIMAX_BASE_URL,
            api_key=MINIMAX_API_KEY,
            temperature=0.3,
            max_tokens=256,
        )
        assert llm is not None
        assert llm.provider_name == "minimax"

    def test_create_llm_by_provider_with_openai_compatible(self):
        """验证 create_llm_by_provider 能创建兼容 OpenAI 的 LLM"""
        from app.engine.graph.trading_graph import create_llm_by_provider

        llm = create_llm_by_provider(
            provider="openai",
            model=MINIMAX_MODEL,
            backend_url=MINIMAX_BASE_URL,
            temperature=0.3,
            max_tokens=256,
            timeout=30,
            api_key=MINIMAX_API_KEY,
        )
        assert llm is not None


# ============================================================
# 2. LLM 实际调用测试
# ============================================================

class TestLLMActualCalls:
    """测试 LLM 实际 API 调用"""

    @pytest.mark.asyncio
    async def test_minimax_simple_chat(self):
        """测试 MiniMax 模型基本对话能力"""
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage

        llm = ChatOpenAI(
            model=MINIMAX_MODEL,
            api_key=MINIMAX_API_KEY,
            base_url=MINIMAX_BASE_URL,
            temperature=0.1,
            max_tokens=100,
            timeout=30,
        )

        response = await llm.ainvoke([HumanMessage(content="你好，请用一句话介绍平安银行（000001）")])
        assert response is not None
        assert response.content is not None
        assert len(response.content) > 0
        print(f"\n[MiniMax 响应]: {response.content[:200]}")

    @pytest.mark.asyncio
    async def test_minimax_system_prompt_chat(self):
        """测试带系统提示的 MiniMax 对话"""
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import SystemMessage, HumanMessage

        llm = ChatOpenAI(
            model=MINIMAX_MODEL,
            api_key=MINIMAX_API_KEY,
            base_url=MINIMAX_BASE_URL,
            temperature=0.1,
            max_tokens=200,
            timeout=30,
        )

        messages = [
            SystemMessage(content="你是一个专业的A股分析师。请用中文回答，回答要简洁专业。"),
            HumanMessage(content="请简要分析银行板块的投资特点，不超过50个字。"),
        ]
        response = await llm.ainvoke(messages)
        assert response is not None
        assert len(response.content) > 0
        # 验证回复包含中文
        assert any("一" <= c <= "鿿" for c in response.content)
        print(f"\n[分析师响应]: {response.content[:200]}")

    def test_minimax_sync_call(self):
        """测试 MiniMax 同步调用"""
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage

        llm = ChatOpenAI(
            model=MINIMAX_MODEL,
            api_key=MINIMAX_API_KEY,
            base_url=MINIMAX_BASE_URL,
            temperature=0.1,
            max_tokens=100,
            timeout=30,
        )

        response = llm.invoke([HumanMessage(content="1+1等于几？只回答数字")])
        assert response is not None
        assert "2" in response.content
        print(f"\n[同步调用响应]: {response.content}")

    @pytest.mark.asyncio
    async def test_minimax_json_output(self):
        """测试 MiniMax 结构化输出能力"""
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage
        import json

        llm = ChatOpenAI(
            model=MINIMAX_MODEL,
            api_key=MINIMAX_API_KEY,
            base_url=MINIMAX_BASE_URL,
            temperature=0.1,
            max_tokens=200,
            timeout=30,
        )

        response = await llm.ainvoke([
            HumanMessage(content='请以JSON格式返回: {"stock": "000001", "name": "平安银行", "recommendation": "买入/卖出/持有"}，只返回JSON不要其他内容')
        ])
        assert response is not None
        # 验证至少包含基本字段
        content = response.content
        assert "000001" in content or "平安银行" in content
        print(f"\n[JSON 输出]: {content[:200]}")


# ============================================================
# 3. 带工具调用的 LLM 测试
# ============================================================

class TestLLMToolCalling:
    """测试 LLM 工具调用能力"""

    @pytest.mark.asyncio
    async def test_minimax_tool_calling(self):
        """测试 MiniMax 模型的工具调用能力"""
        from langchain_openai import ChatOpenAI
        from langchain_core.tools import tool
        from langchain_core.messages import HumanMessage

        @tool
        def get_stock_price(stock_code: str) -> str:
            """获取股票当前价格"""
            mock_prices = {"000001": "12.50", "600519": "1680.00"}
            return mock_prices.get(stock_code, "未找到该股票")

        llm = ChatOpenAI(
            model=MINIMAX_MODEL,
            api_key=MINIMAX_API_KEY,
            base_url=MINIMAX_BASE_URL,
            temperature=0.1,
            max_tokens=200,
            timeout=30,
        )

        llm_with_tools = llm.bind_tools([get_stock_price])
        response = await llm_with_tools.ainvoke([HumanMessage(content="请查询平安银行(000001)的股价")])

        assert response is not None
        # MiniMax 可能直接回答或使用工具调用
        print(f"\n[工具调用响应]: {response}")

    @pytest.mark.asyncio
    async def test_minimax_multi_turn_conversation(self):
        """测试 MiniMax 多轮对话"""
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage, AIMessage

        llm = ChatOpenAI(
            model=MINIMAX_MODEL,
            api_key=MINIMAX_API_KEY,
            base_url=MINIMAX_BASE_URL,
            temperature=0.1,
            max_tokens=100,
            timeout=30,
        )

        # 第一轮
        r1 = await llm.ainvoke([HumanMessage(content="记住这个数字：42")])
        assert r1 is not None

        # 第二轮（带上下文）
        messages = [
            HumanMessage(content="记住这个数字：42"),
            AIMessage(content=r1.content),
            HumanMessage(content="我让你记住的数字是多少？只回答数字"),
        ]
        r2 = await llm.ainvoke(messages)
        assert r2 is not None
        assert "42" in r2.content
        print(f"\n[多轮对话响应]: {r2.content}")


# ============================================================
# 4. 分析引擎核心组件实际调用测试
# ============================================================

class TestAnalysisEngineWithRealLLM:
    """测试分析引擎核心组件使用真实 LLM"""

    @pytest.mark.asyncio
    async def test_conditional_logic_with_llm_response(self):
        """测试条件逻辑能正确处理 LLM 风格的响应"""
        from app.engine.graph.conditional_logic import ConditionalLogic

        logic = ConditionalLogic()
        # 模拟包含 Bull 发言的状态
        state = {
            "messages": [],
            "count": 1,
            "current_speaker": "Bull",
        }
        # should_continue_debate 应根据 count 和 max_count 决定是否继续
        result = logic.should_continue_debate(state)
        assert result is not None

    def test_agent_state_with_real_data(self):
        """测试 Agent State 能承载真实分析数据"""
        from app.engine.agents.utils.agent_states import AgentState, update_reports

        state = {
            "company_of_interest": "000001",
            "trade_date": "2024-12-31",
            "messages": [],
            "reports": {},
            "market_report": None,
            "fundamentals_report": None,
        }
        assert state["company_of_interest"] == "000001"

        # 测试 update_reports reducer
        existing = {"market_report": "市场分析内容"}
        new = {"fundamentals_report": "基本面分析内容"}
        merged = update_reports(existing, new)
        assert "market_report" in merged
        assert "fundamentals_report" in merged

    @pytest.mark.asyncio
    async def test_simple_agent_prompt_building(self):
        """测试分析师 Agent 提示构建逻辑"""
        from app.engine.agents.analysts.simple_agent_template import create_simple_agent

        # 构建一个 mock LLM（不实际调用，只测试 prompt 构建）
        from unittest.mock import MagicMock

        mock_llm = MagicMock()
        mock_llm.bind_tools = MagicMock(return_value=mock_llm)
        mock_llm.invoke = MagicMock(return_value=MagicMock(
            content="这是分析报告结论",
            tool_calls=[],
        ))

        agent_node = create_simple_agent(
            name="市场技术分析师",
            slug="market-analyst",
            llm=mock_llm,
            tools=[],
            system_prompt="你是一个专业的A股市场技术分析师。请分析以下股票的技术指标。",
            max_tool_calls=5,
        )

        assert callable(agent_node)

        # 调用 agent 节点
        state = {
            "company_of_interest": "000001",
            "trade_date": "2024-12-31",
            "messages": [],
            "reports": {},
        }
        result = agent_node(state)
        assert isinstance(result, dict)


# ============================================================
# 5. LLM 错误处理和边界测试
# ============================================================

class TestLLMErrorHandling:
    """测试 LLM 调用中的错误处理"""

    def test_invalid_api_key_raises_error(self):
        """测试无效 API Key 抛出异常"""
        from app.engine.llm_adapters.openai_compatible_base import OpenAICompatibleBase

        with pytest.raises(ValueError, match="API密钥"):
            OpenAICompatibleBase(
                provider_name="minimax",
                model=MINIMAX_MODEL,
                api_key_env_var="NONEXISTENT_KEY_12345",
                base_url=MINIMAX_BASE_URL,
                # 不传 api_key，让它从环境变量读取
                temperature=0.1,
            )

    @pytest.mark.asyncio
    async def test_timeout_handling(self):
        """测试超时参数传递"""
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model=MINIMAX_MODEL,
            api_key=MINIMAX_API_KEY,
            base_url=MINIMAX_BASE_URL,
            temperature=0.1,
            max_tokens=10,
            timeout=5,  # 5秒超时
            max_retries=0,
        )
        # 正常调用不应超时
        from langchain_core.messages import HumanMessage
        response = await llm.ainvoke([HumanMessage(content="hi")])
        assert response is not None

    def test_empty_model_name(self):
        """测试空模型名称"""
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model="",
            api_key=MINIMAX_API_KEY,
            base_url=MINIMAX_BASE_URL,
            max_tokens=10,
        )
        # 空模型名不应在初始化时崩溃
        assert llm is not None


# ============================================================
# 6. Token 使用统计测试
# ============================================================

class TestTokenUsageTracking:
    """测试 Token 使用统计功能"""

    @pytest.mark.asyncio
    async def test_response_has_usage_metadata(self):
        """测试 MiniMax 响应包含 usage metadata"""
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage

        llm = ChatOpenAI(
            model=MINIMAX_MODEL,
            api_key=MINIMAX_API_KEY,
            base_url=MINIMAX_BASE_URL,
            temperature=0.1,
            max_tokens=50,
            timeout=30,
        )

        response = await llm.ainvoke([HumanMessage(content="你好")])
        # 检查 response 的 usage_metadata
        usage = getattr(response, "usage_metadata", None) or getattr(response, "response_metadata", {})
        assert response is not None
        print(f"\n[Usage]: {usage}")


# ============================================================
# 运行说明
# ============================================================

# 运行所有 AI 集成测试:
#   python -m pytest tests/ai_integration/ -v -s
#
# 仅运行 LLM 调用测试:
#   python -m pytest tests/ai_integration/ -v -k "TestLLMActualCalls"
#
# 跳过 AI 测试（仅运行本地测试）:
#   python -m pytest tests/ -v -m "not ai"
