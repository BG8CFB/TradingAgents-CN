"""Toolkit 聚合门面 — 保留对外兼容接口，实现委托到子模块。"""

from typing import List
from typing import Annotated

from langchain_core.messages import HumanMessage, AIMessage, RemoveMessage
from langchain_core.tools import tool

from app.engine.default_config import DEFAULT_CONFIG
from app.utils.logging_init import get_logger

# 从子模块导入所有工具函数
from .toolkit_news import (
    get_finnhub_news,
    get_reddit_stock_info,
    get_realtime_stock_news,
    get_stock_news_unified,
)
from .toolkit_market import get_china_market_overview, get_stock_market_data_unified
from .toolkit_fundamentals import get_stock_fundamentals_unified
from .toolkit_sentiment import get_stock_sentiment_unified

logger = get_logger("agents")


def create_msg_delete():
    def delete_messages(state):
        """Clear messages and add placeholder for Anthropic compatibility"""
        messages = state["messages"]

        # Remove all messages
        removal_operations = [RemoveMessage(id=m.id) for m in messages]

        # Add a minimal placeholder message
        placeholder = HumanMessage(content="Continue")

        return {"messages": removal_operations + [placeholder]}

    return delete_messages


class Toolkit:
    """聚合门面 — 将所有 @tool 方法委托到子模块中的独立函数。

    公共接口（属性 + 方法签名）与重构前完全一致。
    """

    _config = DEFAULT_CONFIG.copy()

    @classmethod
    def update_config(cls, config):
        """Update the class-level configuration."""
        cls._config.update(config)

    @property
    def config(self):
        """Access the configuration."""
        return self._config

    @property
    def enable_mcp(self):
        return self._config.get("enable_mcp", False)

    @property
    def mcp_tool_loader(self):
        return self._config.get("mcp_tool_loader", None)

    def __init__(self, config=None):
        if config:
            self.update_config(config)

    # ── 新闻工具 ──────────────────────────────────────────────────
    get_finnhub_news = staticmethod(get_finnhub_news)
    get_reddit_stock_info = staticmethod(get_reddit_stock_info)
    get_realtime_stock_news = staticmethod(get_realtime_stock_news)
    get_stock_news_unified = staticmethod(get_stock_news_unified)

    # ── 市场工具 ──────────────────────────────────────────────────
    get_china_market_overview = staticmethod(get_china_market_overview)
    get_stock_market_data_unified = staticmethod(get_stock_market_data_unified)

    # ── 基本面工具 ────────────────────────────────────────────────
    get_stock_fundamentals_unified = staticmethod(get_stock_fundamentals_unified)

    # ── 情绪工具 ──────────────────────────────────────────────────
    get_stock_sentiment_unified = staticmethod(get_stock_sentiment_unified)
