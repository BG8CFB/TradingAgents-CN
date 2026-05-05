"""
子图架构验证测试

测试目标：
1. 验证 DynamicAnalystFactory 配置加载和查找
2. 验证 GraphSetup 可以正确编译工作流
3. 验证分析师配置结构正确
4. 验证进度管理器功能

注意：这是架构验证测试，不运行完整的分析流程。
"""

import pytest
from typing import Dict, Any

from unittest.mock import MagicMock, patch

from app.engine.agents.analysts.dynamic_analyst import DynamicAnalystFactory, ProgressManager
from app.engine.graph.conditional_logic import ConditionalLogic

# 测试用模拟配置数据
MOCK_CONFIG = {
    "customModes": [
        {
            "slug": "market-analyst",
            "name": "市场技术分析师",
            "roleDefinition": "分析市场技术指标",
        },
        {
            "slug": "fundamentals-analyst",
            "name": "基本面分析师",
            "roleDefinition": "分析基本面数据",
        },
    ]
}


class TestDynamicAnalystFactory:
    """测试 DynamicAnalystFactory 配置加载和查找"""

    @patch.object(DynamicAnalystFactory, "load_config", return_value=MOCK_CONFIG)
    def test_get_agent_config_returns_config_for_known_slug(self, mock_load):
        """测试已知 slug 可以正确返回配置"""
        config = DynamicAnalystFactory.get_agent_config("market-analyst")

        assert config is not None, "应该能读取到 market-analyst 的配置"
        assert "name" in config, "配置应该包含 name 字段"
        assert "slug" in config, "配置应该包含 slug 字段"
        assert config["slug"] == "market-analyst"

    def test_get_agent_config_returns_none_for_unknown_slug(self):
        """测试未知 slug 返回 None"""
        config = DynamicAnalystFactory.get_agent_config("nonexistent-analyst")
        assert config is None

    @patch.object(DynamicAnalystFactory, "load_config", return_value=MOCK_CONFIG)
    def test_get_all_agents_returns_list(self, mock_load):
        """测试 get_all_agents 返回列表"""
        agents = DynamicAnalystFactory.get_all_agents()
        assert isinstance(agents, list)
        assert len(agents) > 0, "应至少有一个分析师配置"

    @patch.object(DynamicAnalystFactory, "load_config", return_value=MOCK_CONFIG)
    def test_all_agents_have_required_fields(self, mock_load):
        """测试所有分析师配置都有必要字段"""
        agents = DynamicAnalystFactory.get_all_agents()
        required_fields = {"slug", "name"}

        for agent in agents:
            missing = required_fields - set(agent.keys())
            assert not missing, f"分析师 {agent.get('name', '?')} 缺少字段: {missing}"

    @patch.object(DynamicAnalystFactory, "load_config", return_value=MOCK_CONFIG)
    def test_all_agent_slugs_are_unique(self, mock_load):
        """测试所有分析师 slug 唯一"""
        agents = DynamicAnalystFactory.get_all_agents()
        slugs = [a.get("slug") for a in agents if a.get("slug")]
        assert len(slugs) == len(set(slugs)), "分析师 slug 应该唯一"

    @patch.object(DynamicAnalystFactory, "load_config", return_value=MOCK_CONFIG)
    def test_get_slug_by_name(self, mock_load):
        """测试通过中文名称查找 slug"""
        agents = DynamicAnalystFactory.get_all_agents()
        if agents:
            first = agents[0]
            name = first.get("name")
            if name:
                slug = DynamicAnalystFactory.get_slug_by_name(name)
                assert slug is not None
                assert slug == first.get("slug")

    @patch.object(DynamicAnalystFactory, "load_config", return_value=MOCK_CONFIG)
    def test_get_agent_config_by_internal_key(self, mock_load):
        """测试通过 internal_key 查找配置"""
        config = DynamicAnalystFactory.get_agent_config("market")
        # "market" 是 "market-analyst" 的 internal_key
        assert config is not None, "应能通过 internal_key 找到配置"

    @patch.object(DynamicAnalystFactory, "load_config", return_value=MOCK_CONFIG)
    def test_load_config_returns_dict(self, mock_load):
        """测试 load_config 返回字典"""
        config = DynamicAnalystFactory.load_config()
        assert isinstance(config, dict)

    @patch.object(DynamicAnalystFactory, "load_config", return_value=MOCK_CONFIG)
    def test_build_lookup_map(self, mock_load):
        """测试构建查找映射"""
        lookup_map = DynamicAnalystFactory.build_lookup_map()
        assert isinstance(lookup_map, dict)
        assert len(lookup_map) > 0


class TestProgressManager:
    """测试进度管理器"""

    def test_set_and_remove_callback(self):
        """测试设置和移除回调"""
        task_id = "test-task-001"
        callback = MagicMock()

        ProgressManager.set_callback(task_id, callback)
        assert task_id in ProgressManager._callbacks

        ProgressManager.remove_callback(task_id)
        assert task_id not in ProgressManager._callbacks

    def test_set_callback_none_removes(self):
        """测试设置 None 回调等于移除"""
        task_id = "test-task-002"
        callback = MagicMock()

        ProgressManager.set_callback(task_id, callback)
        assert task_id in ProgressManager._callbacks

        ProgressManager.set_callback(task_id, None)
        assert task_id not in ProgressManager._callbacks

    def test_multiple_tasks_isolated(self):
        """测试多任务隔离"""
        cb1 = MagicMock()
        cb2 = MagicMock()

        ProgressManager.set_callback("task-1", cb1)
        ProgressManager.set_callback("task-2", cb2)

        assert "task-1" in ProgressManager._callbacks
        assert "task-2" in ProgressManager._callbacks

        ProgressManager.remove_callback("task-1")
        assert "task-1" not in ProgressManager._callbacks
        assert "task-2" in ProgressManager._callbacks

        ProgressManager.remove_callback("task-2")


class TestConditionalLogic:
    """测试条件逻辑"""

    def test_conditional_logic_instantiation(self):
        """测试 ConditionalLogic 可以实例化"""
        logic = ConditionalLogic()
        assert logic is not None


class TestGraphSetup:
    """测试图编译（使用 mock 依赖）"""

    def test_graph_setup_compiles_with_mock_llm(self):
        """测试 GraphSetup 使用 mock LLM 可以编译"""
        from app.engine.graph.setup import GraphSetup
        from app.engine.agents.analysts.simple_agent_factory import SimpleAgentFactory

        mock_llm = MagicMock()
        mock_toolkit = MagicMock()
        mock_toolkit.enable_mcp = False
        mock_toolkit.mcp_tool_loader = None

        # Mock SimpleAgentFactory.create_analysts 返回模拟的分析师节点
        def mock_analyst_node(state):
            return state

        with patch.object(SimpleAgentFactory, "create_analysts", return_value={"market": mock_analyst_node}):
            memories = {k: MagicMock() for k in ["bull", "bear", "trader", "invest_judge", "risk_manager"]}

            graph_setup = GraphSetup(
                quick_thinking_llm=mock_llm,
                deep_thinking_llm=mock_llm,
                toolkit=mock_toolkit,
                bull_memory=memories["bull"],
                bear_memory=memories["bear"],
                trader_memory=memories["trader"],
                invest_judge_memory=memories["invest_judge"],
                risk_manager_memory=memories["risk_manager"],
                conditional_logic=ConditionalLogic(),
                config={"phase2_enabled": False, "phase3_enabled": False, "phase4_enabled": False}
            )

            compiled = graph_setup.setup_graph(selected_analysts=["market-analyst"])
            assert compiled is not None
            assert hasattr(compiled, 'nodes')

            node_names = list(compiled.nodes.keys())
            assert "Market Analyst" in node_names
            assert "Summary Agent" in node_names


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
