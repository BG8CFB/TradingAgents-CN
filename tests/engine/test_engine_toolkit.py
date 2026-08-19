"""测试 Toolkit 工具集"""

from app.engine.agents.utils.agent_utils import Toolkit


class TestToolkitInit:
    def test_default_config(self):
        tk = Toolkit()
        assert isinstance(tk.config, dict)

    def test_custom_config(self):
        tk = Toolkit(config={"custom_key": "value"})
        assert tk.config.get("custom_key") == "value"

    def test_instance_config_isolation(self):
        """两个实例的 config 互不污染（修复点 C2 引擎）。"""
        tk1 = Toolkit(config={"custom_key": "v1"})
        tk2 = Toolkit(config={"custom_key": "v2"})
        assert tk1.config.get("custom_key") == "v1"
        assert tk2.config.get("custom_key") == "v2"
        # 不存在类级别的 update_config
        assert not hasattr(Toolkit, "update_config")


class TestToolkitProperties:
    def test_enable_mcp_default(self):
        tk = Toolkit()
        assert tk.enable_mcp is False

    def test_enable_mcp_set(self):
        tk = Toolkit(config={"enable_mcp": True})
        assert tk.enable_mcp is True

    def test_mcp_tool_loader_default(self):
        tk = Toolkit()
        assert tk.mcp_tool_loader is None

    def test_mcp_tool_loader_set(self):

        class FakeLoader:
            pass

        loader = FakeLoader()
        tk = Toolkit(config={"mcp_tool_loader": loader})
        assert tk.mcp_tool_loader is loader
