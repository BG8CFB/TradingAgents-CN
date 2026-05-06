"""测试 Toolkit 工具集"""

import pytest
from unittest.mock import MagicMock

from app.engine.agents.utils.agent_utils import Toolkit, create_msg_delete


class TestCreateMsgDelete:
    def test_returns_callable(self):
        fn = create_msg_delete()
        assert callable(fn)

    def test_returns_removal_operations_and_placeholder(self):
        fn = create_msg_delete()
        mock_msg1 = MagicMock()
        mock_msg1.id = "msg-1"
        mock_msg2 = MagicMock()
        mock_msg2.id = "msg-2"
        state = {"messages": [mock_msg1, mock_msg2]}
        result = fn(state)
        assert "messages" in result
        msgs = result["messages"]
        assert len(msgs) == 3  # 2 removals + 1 placeholder
        assert msgs[-1].content == "Continue"


class TestToolkitInit:
    def test_default_config(self):
        tk = Toolkit()
        assert isinstance(tk.config, dict)

    def test_custom_config(self):
        tk = Toolkit(config={"custom_key": "value"})
        assert tk.config.get("custom_key") == "value"

    def test_update_config_class_level(self):
        tk1 = Toolkit(config={"test_update": True})
        tk2 = Toolkit()
        assert tk2.config.get("test_update") is True


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
        loader = MagicMock()
        tk = Toolkit(config={"mcp_tool_loader": loader})
        assert tk.mcp_tool_loader is loader
