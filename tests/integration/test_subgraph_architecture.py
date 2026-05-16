"""
子图架构验证测试

测试目标：
1. 验证 DynamicAnalystFactory 配置加载和查找（使用真实配置文件）
2. 验证 GraphSetup 可以正确编译工作流
3. 验证分析师配置结构正确
4. 验证进度管理器功能
"""

import pytest

from app.engine.agents.analysts.dynamic_analyst import DynamicAnalystFactory, ProgressManager
from app.engine.graph.conditional_logic import ConditionalLogic


class TestDynamicAnalystFactory:
    """测试 DynamicAnalystFactory 配置加载和查找（使用真实配置文件）"""

    def test_get_agent_config_returns_none_for_unknown_slug(self):
        """未知 slug 返回 None"""
        config = DynamicAnalystFactory.get_agent_config("nonexistent-analyst")
        assert config is None

    def test_get_all_agents_returns_list(self):
        """get_all_agents 返回列表（从真实配置文件加载）"""
        agents = DynamicAnalystFactory.get_all_agents()
        assert isinstance(agents, list)

    def test_all_agents_have_required_fields(self):
        """所有分析师配置都有必要字段"""
        agents = DynamicAnalystFactory.get_all_agents()
        required_fields = {"slug", "name"}

        for agent in agents:
            missing = required_fields - set(agent.keys())
            assert not missing, f"分析师 {agent.get('name', '?')} 缺少字段: {missing}"

    def test_all_agent_slugs_are_unique(self):
        """所有分析师 slug 唯一"""
        agents = DynamicAnalystFactory.get_all_agents()
        slugs = [a.get("slug") for a in agents if a.get("slug")]
        assert len(slugs) == len(set(slugs)), "分析师 slug 应该唯一"

    def test_get_slug_by_name(self):
        """通过中文名称查找 slug"""
        agents = DynamicAnalystFactory.get_all_agents()
        if agents:
            first = agents[0]
            name = first.get("name")
            if name:
                slug = DynamicAnalystFactory.get_slug_by_name(name)
                assert slug is not None
                assert slug == first.get("slug")

    def test_load_config_returns_dict(self):
        """load_config 返回字典"""
        config = DynamicAnalystFactory.load_config()
        assert isinstance(config, dict)

    def test_build_lookup_map(self):
        """构建查找映射"""
        lookup_map = DynamicAnalystFactory.build_lookup_map()
        assert isinstance(lookup_map, dict)

    def test_build_node_mapping(self):
        """构建节点映射"""
        mapping = DynamicAnalystFactory.build_node_mapping()
        assert isinstance(mapping, dict)


class TestProgressManager:
    """测试进度管理器"""

    def test_set_and_remove_callback(self):
        task_id = "test-task-001"

        def sample_callback(*args, **kwargs):
            pass

        ProgressManager.set_callback(task_id, sample_callback)
        assert task_id in ProgressManager._callbacks

        ProgressManager.remove_callback(task_id)
        assert task_id not in ProgressManager._callbacks

    def test_set_callback_none_removes(self):
        task_id = "test-task-002"

        def sample_callback(*args, **kwargs):
            pass

        ProgressManager.set_callback(task_id, sample_callback)
        assert task_id in ProgressManager._callbacks

        ProgressManager.set_callback(task_id, None)
        assert task_id not in ProgressManager._callbacks

    def test_multiple_tasks_isolated(self):
        def cb1(*args, **kwargs):
            pass

        def cb2(*args, **kwargs):
            pass

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
        logic = ConditionalLogic()
        assert logic is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
