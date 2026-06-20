"""测试 Toolkit 工具集"""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage

from app.engine.agents.utils.agent_utils import Toolkit, create_msg_delete


class TestCreateMsgDelete:
    def test_returns_callable(self):
        fn = create_msg_delete()
        assert callable(fn)

    def test_returns_removal_operations_and_placeholder(self):
        fn = create_msg_delete()
        msg1 = AIMessage(content="hello", id="msg-1")
        msg2 = AIMessage(content="world", id="msg-2")
        state = {"messages": [msg1, msg2]}
        result = fn(state)
        assert "messages" in result
        msgs = result["messages"]
        assert len(msgs) == 3  # 2 removals + 1 placeholder
        assert isinstance(msgs[0], RemoveMessage)
        assert isinstance(msgs[1], RemoveMessage)
        assert isinstance(msgs[2], HumanMessage)
        assert msgs[2].content == "Continue"


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
