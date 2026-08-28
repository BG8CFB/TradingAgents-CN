"""Toolkit 情绪类工具 — get_stock_sentiment_unified。

委托到 app/engine/tools/datasources/sentiment.py 的统一实现（基于新闻舆情
sentiment 标签统计）。历史版本曾返回写死的"功能正在开发中"占位模板，已删除：
占位输出会被 LLM 当作真实数据引用，必须返回真实数据或明确的获取失败。
"""

from typing import Annotated

import logging

from app.utils.tool_logging import log_tool_call

logger = logging.getLogger("agents")


@log_tool_call(tool_name="get_stock_sentiment_unified", log_args=True)
def get_stock_sentiment_unified(
    ticker: Annotated[str, "股票代码（支持A股、港股、美股）"],
    curr_date: Annotated[str, "当前日期，格式：YYYY-MM-DD"],
) -> str:
    """
    统一的股票情绪分析工具（基于新闻舆情 sentiment 标签统计）

    自动识别股票类型（A股、港股、美股）并统计近期新闻的情绪分布。
    注意：系统未接入雪球/股吧等社交平台数据，本工具仅基于新闻舆情数据。

    Args:
        ticker: 股票代码（如：000001、0700.HK、AAPL）
        curr_date: 当前日期（格式：YYYY-MM-DD）

    Returns:
        str: 情绪分析报告
    """
    from app.engine.tools.datasources.sentiment import get_stock_sentiment

    return get_stock_sentiment(ticker, curr_date)
