"""Toolkit 聚合门面 — 保留对外兼容接口，实现委托到子模块。"""


from langchain_core.messages import HumanMessage, RemoveMessage

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

    配置为实例属性（非类变量），保证多任务并发隔离。

    历史问题：``_config`` 曾是类变量 + ``update_config`` 类方法，导致两个
    ``TradingAgentsGraph`` 实例并发分析时 config 互相污染。本版本彻底删除
    类变量 / 类方法，每个实例独立持有 config。
    """

    def __init__(self, config=None):
        # 关键：每次构造都基于 DEFAULT_CONFIG 浅拷贝 + 用户 config 覆盖，
        # 保证不同 Toolkit 实例之间互不影响
        self._config = {**DEFAULT_CONFIG, **(config or {})}

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
