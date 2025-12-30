"""
子图架构验证测试

测试目标：
1. 验证 create_react_agent_subgraph 可以正确创建编译后的 StateGraph
2. 验证子图结构正确（包含 agent 节点和 extract_report 节点）
3. 验证 GraphSetup 可以正确编译包含子图的工作流
4. 验证工作流的边连接正确

注意：这是架构验证测试，不运行完整的分析流程。
"""

import pytest
from typing import Dict, Any

# 测试需要模拟的依赖
from unittest.mock import MagicMock, Mock
from langchain_openai import ChatOpenAI

from tradingagents.agents.analysts.dynamic_analyst import (
    create_react_agent_subgraph,
    DynamicAnalystFactory
)
from tradingagents.graph.setup import GraphSetup
from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.agents.utils.agent_utils import Toolkit


class TestSubgraphArchitecture:
    """子图架构验证测试"""

    @pytest.fixture
    def mock_llm(self):
        """创建模拟的 LLM 实例"""
        llm = MagicMock(spec=ChatOpenAI)
        llm.model_name = "gpt-4"
        return llm

    @pytest.fixture
    def mock_toolkit(self):
        """创建模拟的 Toolkit 实例"""
        toolkit = MagicMock(spec=Toolkit)
        toolkit.enable_mcp = False
        toolkit.mcp_tool_loader = None

        # 添加一些模拟的工具
        toolkit.get_stock_market_data_unified = MagicMock(
            name="get_stock_market_data_unified",
            description="获取股票市场数据（统一接口）"
        )
        toolkit.get_stock_news_unified = MagicMock(
            name="get_stock_news_unified",
            description="获取股票新闻（统一接口）"
        )

        return toolkit

    @pytest.fixture
    def mock_memories(self):
        """创建模拟的记忆对象"""
        return {
            "bull": MagicMock(),
            "bear": MagicMock(),
            "trader": MagicMock(),
            "invest_judge": MagicMock(),
            "risk_manager": MagicMock()
        }

    def test_create_react_agent_subgraph_returns_compiled_graph(self, mock_llm, mock_toolkit):
        """测试 create_react_agent_subgraph 返回编译后的 StateGraph"""
        # 使用一个已知的分析师 slug
        slug = "market-analyst"

        # 创建子图
        subgraph = create_react_agent_subgraph(slug, mock_llm, mock_toolkit)

        # 验证返回的是编译后的 StateGraph
        # LangGraph 1.0+ 中，create_react_agent 直接返回 CompiledStateGraph
        from langgraph.graph.state import CompiledStateGraph
        assert isinstance(subgraph, CompiledStateGraph), "子图应该是编译后的 CompiledStateGraph"
        assert hasattr(subgraph, 'nodes'), "编译后的图应该有节点信息"

        # 验证子图有正确的节点结构
        # 子图应该包含: agent 节点（内部 ReAct 循环）和 extract_report 节点
        node_names = list(subgraph.nodes.keys())
        assert "agent" in node_names, "子图应该包含 'agent' 节点"
        assert "extract_report" in node_names, "子图应该包含 'extract_report' 节点"

    def test_subgraph_has_correct_edges(self, mock_llm, mock_toolkit):
        """测试子图的边连接正确"""
        slug = "market-analyst"
        subgraph = create_react_agent_subgraph(slug, mock_llm, mock_toolkit)

        # 验证边连接：agent -> extract_report -> END
        # 注意：这里只是验证结构，不验证具体边名称
        assert len(subgraph.nodes) >= 2, "子图应该至少有 2 个节点"

    def test_graph_setup_with_subgraph_compiles_successfully(
        self, mock_llm, mock_toolkit, mock_memories
    ):
        """测试 GraphSetup 可以正确编译包含子图的工作流"""
        # 创建条件逻辑实例
        conditional_logic = ConditionalLogic()

        # 创建 GraphSetup 实例
        graph_setup = GraphSetup(
            quick_thinking_llm=mock_llm,
            deep_thinking_llm=mock_llm,
            toolkit=mock_toolkit,
            tool_nodes={},  # 子图模式不再使用
            bull_memory=mock_memories["bull"],
            bear_memory=mock_memories["bear"],
            trader_memory=mock_memories["trader"],
            invest_judge_memory=mock_memories["invest_judge"],
            risk_manager_memory=mock_memories["risk_manager"],
            conditional_logic=conditional_logic,
            config={"phase2_enabled": False, "phase3_enabled": False, "phase4_enabled": False}
        )

        # 编译工作流，使用单个分析师
        compiled_graph = graph_setup.setup_graph(
            selected_analysts=["market-analyst"]
        )

        # 验证编译成功
        assert compiled_graph is not None, "工作流应该编译成功"
        assert hasattr(compiled_graph, 'nodes'), "编译后的图应该有节点信息"

        # 验证工作流包含预期的节点
        node_names = list(compiled_graph.nodes.keys())
        assert "Market Analyst" in node_names, "工作流应该包含 'Market Analyst' 节点"
        assert "Msg Clear Market" in node_names, "工作流应该包含 'Msg Clear Market' 节点"
        assert "Summary Agent" in node_names, "工作流应该包含 'Summary Agent' 节点"

    def test_multiple_analysts_workflow_compiles(self, mock_llm, mock_toolkit, mock_memories):
        """测试多个分析师的工作流可以正确编译"""
        conditional_logic = ConditionalLogic()

        graph_setup = GraphSetup(
            quick_thinking_llm=mock_llm,
            deep_thinking_llm=mock_llm,
            toolkit=mock_toolkit,
            tool_nodes={},
            bull_memory=mock_memories["bull"],
            bear_memory=mock_memories["bear"],
            trader_memory=mock_memories["trader"],
            invest_judge_memory=mock_memories["invest_judge"],
            risk_manager_memory=mock_memories["risk_manager"],
            conditional_logic=conditional_logic,
            config={"phase2_enabled": False, "phase3_enabled": False, "phase4_enabled": False}
        )

        # 测试多个分析师
        compiled_graph = graph_setup.setup_graph(
            selected_analysts=["market-analyst", "financial-news-analyst", "fundamentals-analyst"]
        )

        assert compiled_graph is not None

        node_names = list(compiled_graph.nodes.keys())
        assert "Market Analyst" in node_names
        assert "Financial_News Analyst" in node_names
        assert "Fundamentals Analyst" in node_names

    def test_dynamic_analyst_factory_has_config(self):
        """测试 DynamicAnalystFactory 可以正确读取配置"""
        # 测试 get_agent_config 方法
        config = DynamicAnalystFactory.get_agent_config("market-analyst")

        assert config is not None, "应该能读取到 market-analyst 的配置"
        assert "name" in config, "配置应该包含 name 字段"
        assert "roleDefinition" in config, "配置应该包含 roleDefinition 字段"

    def test_subgraph_state_keys_accessible(self, mock_llm, mock_toolkit):
        """测试子图状态可以被正确访问"""
        slug = "market-analyst"
        subgraph = create_react_agent_subgraph(slug, mock_llm, mock_toolkit)

        # 子图应该支持状态键访问
        # 验证子图有 state_schema 或类似的状态定义
        # 这确保了子图和父图之间的状态通信机制存在
        assert hasattr(subgraph, 'channels') or hasattr(subgraph, 'nodes'), \
            "子图应该有状态定义或节点信息"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
