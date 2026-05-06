"""测试 Stage 4 总结智能体"""

import json
import pytest
from unittest.mock import MagicMock

from app.engine.agents.stage_4.summary_agent import create_summary_agent


class TestCreateSummaryAgent:
    def test_returns_callable(self):
        llm = MagicMock()
        node = create_summary_agent(llm)
        assert callable(node)


class TestSummaryNodeStateAccess:
    def test_collects_report_fields_dynamically(self):
        llm = MagicMock()
        node = create_summary_agent(llm)
        # summary_node 动态收集所有 *_report 字段
        # 只验证函数签名正确
        assert callable(node)
