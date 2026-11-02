"""
新闻工具 - 股票新闻数据获取
"""

import logging
from datetime import datetime

from app.utils.time_utils import now_utc
from app.engine.tools.common.tool_result import (
    success_result,
    no_data_result,
    error_result,
    format_tool_result,
    ErrorCodes,
)
from app.engine.tools.common.data_access import read_with_refresh

logger = logging.getLogger(__name__)


def _get_market_for_code(symbol: str) -> str:
    """根据股票代码判断市场。"""
    try:
        from app.utils.stock_utils import StockUtils

        market_info = StockUtils.get_market_info(symbol)
        if market_info.get("is_hk"):
            return "HK"
        if market_info.get("is_us"):
            return "US"
    except Exception as e:
        logger.debug(f"市场类型检测失败，默认CN: {e}")
        pass
    return "CN"


def _fetch_news_data(symbol: str, max_results: int = 10) -> list:
    """内部辅助函数：通过 DataInterface 获取新闻数据列表（库空自动补数重读）。"""
    news_list = []
    market = _get_market_for_code(symbol)

    try:
        result = read_with_refresh(market, "news", symbol=symbol)
        data = result.get("data") if result else None
        source_tag = "Refreshed" if result and result.get("auto_refreshed") else "DB"
        for item in (data or [])[:max_results]:
            news_list.append(
                {
                    "title": item.get("title", "无标题"),
                    "content": item.get("content", ""),
                    "source": f"{item.get('data_source', item.get('source', '未知'))} ({source_tag})",
                    "publish_time": item.get("publish_time", now_utc()),
                    "sentiment": item.get("sentiment", "neutral"),
                    "url": item.get("url", ""),
                }
            )
        if news_list:
            logger.info(f"[新闻工具] 数据库缓存命中: {len(news_list)} 条")
    except Exception as e:
        logger.warning(f"[新闻工具] 通过 DataInterface 获取失败: {e}")

    return news_list


def _format_news_list(news_list: list, source_label: str = None) -> str:
    """格式化新闻列表为 Markdown"""
    if not news_list:
        return "暂无新闻数据"

    report = f"# 最新新闻 {'(' + source_label + ')' if source_label else ''}\n\n"
    report += f"查询时间: {now_utc().strftime('%Y-%m-%d %H:%M:%S')}\n"
    report += f"新闻数量: {len(news_list)} 条\n\n"

    for i, news in enumerate(news_list, 1):
        title = news.get("title", "无标题")
        content = news.get("content", "")
        source = news.get("source", "未知来源")
        pub_time = news.get("publish_time", now_utc())
        if isinstance(pub_time, datetime):
            pub_time_str = pub_time.strftime("%Y-%m-%d %H:%M")
        else:
            pub_time_str = str(pub_time)

        sentiment = news.get("sentiment", "neutral")

        report += f"## {i}. {title}\n\n"
        report += f"**来源**: {source} | **时间**: {pub_time_str}\n"
        if sentiment:
            report += f"**情绪**: {sentiment}\n"
        report += "\n"

        if content:
            # 内容全量返回，不截断：新闻正文是分析师的信息源，截断会丢关键事实
            report += f"{content}\n\n"

        report += "---\n\n"

    return report


def _fetch_market_news(max_results: int) -> list:
    """读取市场快讯兜底（symbol 为空的全市场新闻），来源标注为市场新闻。"""
    try:
        from app.data.core.interface import DataInterface
        from app.core.async_utils import run_async

        di = DataInterface.get_instance()
        result = run_async(di.read("CN", "news", filters={"limit": max_results}))
        data = result.get("data")
        if not data or not isinstance(data, list):
            return []
        out = []
        for item in data[:max_results]:
            out.append(
                {
                    "title": item.get("title", "无标题"),
                    "content": item.get("content", ""),
                    "source": f"{item.get('data_source', item.get('source', '未知'))} (市场新闻,非个股)",
                    "publish_time": item.get("publish_time", now_utc()),
                    "sentiment": item.get("sentiment", "neutral"),
                    "url": item.get("url", ""),
                }
            )
        if out:
            logger.info(f"[新闻工具] 市场新闻兜底: {len(out)} 条")
        return out
    except Exception as e:
        logger.warning(f"[新闻工具] 市场新闻兜底失败: {e}")
        return []


def _filter_news_asof(news_list: list, as_of: str) -> list:
    """按分析基准日过滤新闻：发布日期晚于 as_of 的一律剔除（防前视）。

    publish_time 缺失或无法解析时保留该条（缺失元数据不是泄密的证据，
    强行剔除会误伤无时间戳的存量语料）。
    """
    if not as_of:
        return news_list
    cutoff = as_of[:10]
    out = []
    for item in news_list:
        pub = item.get("publish_time")
        if isinstance(pub, datetime):
            day = pub.strftime("%Y-%m-%d")
        elif isinstance(pub, str) and len(pub) >= 10:
            day = pub[:10]
        else:
            out.append(item)
            continue
        if day <= cutoff:
            out.append(item)
    return out


def get_stock_news(symbol: str, max_results: int = 10, current_date: str = None) -> str:
    """
    获取指定股票的最新新闻。

    返回格式化的新闻列表，包含标题、来源、时间和摘要。

    Args:
        symbol: 股票代码，如 "000001.SZ"(A股)、"AAPL"(美股)、"00700.HK"(港股)
        max_results: 返回的最大新闻数，建议范围 5-20，默认 10
        current_date: 分析基准日（注入 trade_date）；发布晚于该日的新闻被剔除，防止历史分析前视

    Returns:
        JSON 格式的 ToolResult，包含 status、data、error_code、suggestion 字段
    """
    if not symbol:
        return format_tool_result(error_result(ErrorCodes.MISSING_PARAM, "未提供股票代码"))

    try:
        news_list = _fetch_news_data(symbol, max_results)
        news_list = _filter_news_asof(news_list, current_date)

        if news_list:
            source = news_list[0].get("source", "Unknown")
            if "(DB)" in source:
                source_label = "数据库缓存"
            elif "(Refreshed)" in source:
                source_label = "实时刷新"
            else:
                source_label = "聚合数据"

            return format_tool_result(success_result(_format_news_list(news_list, source_label)))

        # 兜底：个股新闻无数据时，回退到市场快讯（库里大量新闻挂在空 symbol 下），
        # 让分析师至少有市场面信息可用，而不是直接 no_data 结束。
        market_news = _filter_news_asof(_fetch_market_news(max_results), current_date)
        if market_news:
            return format_tool_result(success_result(
                _format_news_list(market_news, f"市场新闻兜底（未找到 {symbol} 个股新闻）")
            ))

        return format_tool_result(
            no_data_result(message=f"未找到 {symbol} 的新闻数据", suggestion="这是正常状态，不要重试或尝试其他参数")
        )
    except Exception as e:
        logger.error(f"get_stock_news failed: {e}", exc_info=True)
        return format_tool_result(error_result(ErrorCodes.DATA_FETCH_ERROR, str(e)))
