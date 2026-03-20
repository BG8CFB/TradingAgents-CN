"""
新闻工具 - 股票新闻、财经新闻、7x24快讯、时间戳
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from app.utils.time_utils import now_utc, get_current_date, get_current_date_compact
from app.engine.tools.builtin.standard import success_result, no_data_result, error_result, format_tool_result, ErrorCodes
from app.engine.tools.builtin.helpers import get_manager, format_result

logger = logging.getLogger(__name__)


def _fetch_news_data(stock_code: str, max_results: int = 10) -> list:
    """内部辅助函数：获取原始新闻数据列表"""
    news_list = []

    try:
        from app.utils.stock_utils import StockUtils
        market_info = StockUtils.get_market_info(stock_code)
        is_china = market_info['is_china']
        is_hk = market_info['is_hk']
        is_us = market_info['is_us']
    except Exception as e:
        logger.warning(f"[MCP新闻工具] 股票类型识别失败: {e}")
        is_china, is_hk, is_us = True, False, False

    # 1. 优先从数据库获取 (所有市场)
    try:
        from app.data.cache.app_adapter import get_mongodb_client
        client = get_mongodb_client()
        if client:
            db = client.get_database('tradingagents')
            collection = db.stock_news

            clean_code = stock_code.replace('.SH', '').replace('.SZ', '').replace('.SS', '')\
                                   .replace('.XSHE', '').replace('.XSHG', '').replace('.HK', '')

            thirty_days_ago = now_utc() - timedelta(days=30)
            query_list = [
                {'symbol': clean_code, 'publish_time': {'$gte': thirty_days_ago}},
                {'symbol': stock_code, 'publish_time': {'$gte': thirty_days_ago}},
            ]

            for query in query_list:
                cursor = collection.find(query).sort('publish_time', -1).limit(max_results)
                db_items = list(cursor)
                if db_items:
                    logger.info(f"[MCP新闻工具] ✅ 数据库缓存命中: {len(db_items)} 条")
                    for item in db_items:
                        news_list.append({
                            'title': item.get('title', '无标题'),
                            'content': item.get('content', '') or item.get('summary', ''),
                            'source': f"{item.get('source', '未知')} (DB)",
                            'publish_time': item.get('publish_time', now_utc()),
                            'sentiment': item.get('sentiment', 'neutral'),
                            'url': item.get('url', '')
                        })
                    return news_list
    except Exception as e:
        logger.warning(f"[MCP新闻工具] 数据库获取失败: {e}")

    # 2. 外部数据源

    # --- A股 & 港股 ---
    if is_china or is_hk:
        clean_code = stock_code.replace('.SH', '').replace('.SZ', '').replace('.SS', '')\
                               .replace('.XSHE', '').replace('.XSHG', '').replace('.HK', '')

        # 2.1 尝试 Tushare
        try:
            from app.data.providers.china.tushare import TushareProvider

            ts_provider = TushareProvider()
            if ts_provider.is_available():
                logger.info(f"🔄 尝试 Tushare 新闻: {stock_code}")
                if hasattr(ts_provider, 'pro') and ts_provider.pro:
                    start_dt = (now_utc() - timedelta(days=30)).strftime('%Y%m%d')
                    end_dt = get_current_date_compact()

                    df = ts_provider.pro.news(src='sina', symbol=clean_code, start_date=start_dt, end_date=end_dt)
                    if df is not None and not df.empty:
                         df = df.sort_values('datetime', ascending=False).head(max_results)

                         for _, row in df.iterrows():
                             news_list.append({
                                 'title': row.get('title', '无标题'),
                                 'content': row.get('content', ''),
                                 'source': 'Tushare (Sina)',
                                 'publish_time': row.get('datetime', now_utc()),
                                 'sentiment': 'neutral',
                                 'url': ''
                             })
                         logger.info(f"✅ Tushare 获取新闻成功: {len(news_list)} 条")
                         return news_list
        except Exception as e:
            logger.warning(f"[MCP新闻工具] Tushare 获取失败: {e}")

        # 2.2 尝试 AKShare
        try:
            from app.data.providers.china.akshare import AKShareProvider
            import asyncio
            import concurrent.futures

            provider = AKShareProvider()

            def run_async():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    return loop.run_until_complete(provider.get_stock_news(symbol=clean_code, limit=max_results))
                finally:
                    loop.close()

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(run_async)
                ak_news = future.result(timeout=30)

            if ak_news:
                for item in ak_news:
                    news_list.append({
                        'title': item.get('title', ''),
                        'content': item.get('content', '') or item.get('summary', ''),
                        'source': f"{item.get('source', 'AKShare')}",
                        'publish_time': item.get('publish_time', now_utc()),
                        'sentiment': item.get('sentiment', 'neutral'),
                        'url': item.get('url', '')
                    })
                return news_list
        except Exception as e:
            logger.warning(f"[MCP新闻工具] AKShare 获取失败: {e}")

    # --- 美股 ---
    if is_us:
        # 2.3 Finnhub
        try:
            from app.data.interface import get_finnhub_news
            logger.info(f"🔄 尝试 Finnhub 新闻: {stock_code}")
            current_date_str = get_current_date()
            finnhub_news_str = get_finnhub_news(stock_code, current_date_str, 7)

            if finnhub_news_str and "暂无" not in finnhub_news_str and "Error" not in finnhub_news_str:
                 news_list.append({
                     'title': 'Finnhub News Summary',
                     'content': finnhub_news_str,
                     'source': 'Finnhub',
                     'publish_time': now_utc(),
                     'sentiment': 'neutral'
                 })
                 return news_list
        except Exception as e:
            logger.warning(f"[MCP新闻工具] Finnhub 获取失败: {e}")

        # 2.4 Google News (Fallback)
        try:
            from app.data.interface import get_google_news
            logger.info(f"🔄 尝试 Google News: {stock_code}")
            current_date_str = get_current_date()
            google_news_str = get_google_news(stock_code, current_date_str, 7)

            if google_news_str and "暂无" not in google_news_str:
                 news_list.append({
                     'title': 'Google News Summary',
                     'content': google_news_str,
                     'source': 'Google News',
                     'publish_time': now_utc(),
                     'sentiment': 'neutral'
                 })
                 return news_list
        except Exception as e:
            logger.warning(f"[MCP新闻工具] Google News 获取失败: {e}")

    return news_list


def _format_news_list(news_list: list, source_label: str = None) -> str:
    """格式化新闻列表为 Markdown"""
    if not news_list:
        return "暂无新闻数据"

    report = f"# 最新新闻 {'(' + source_label + ')' if source_label else ''}\n\n"
    report += f"📅 查询时间: {now_utc().strftime('%Y-%m-%d %H:%M:%S')}\n"
    report += f"📊 新闻数量: {len(news_list)} 条\n\n"

    for i, news in enumerate(news_list, 1):
        title = news.get('title', '无标题')
        content = news.get('content', '')
        source = news.get('source', '未知来源')
        pub_time = news.get('publish_time', now_utc())
        if isinstance(pub_time, datetime):
            pub_time_str = pub_time.strftime('%Y-%m-%d %H:%M')
        else:
            pub_time_str = str(pub_time)

        sentiment = news.get('sentiment', 'neutral')
        sentiment_icon = {'positive': '📈', 'negative': '📉', 'neutral': '➖'}.get(sentiment, '➖')

        report += f"## {i}. {sentiment_icon} {title}\n\n"
        report += f"**来源**: {source} | **时间**: {pub_time_str}\n"
        if sentiment:
            report += f"**情绪**: {sentiment}\n"
        report += "\n"

        if content:
            if len(content) > 1000 and "===" in content:
                report += content
            else:
                content_preview = content[:500] + '...' if len(content) > 500 else content
                report += f"{content_preview}\n\n"

        report += "---\n\n"

    return report


def get_stock_news(
    stock_code: str,
    max_results: int = 10
) -> str:
    """
    获取指定股票的最新新闻。

    返回格式化的新闻列表，包含标题、来源、时间和摘要。

    Args:
        stock_code: 股票代码，如 "000001.SZ"(A股)、"AAPL"(美股)、"00700.HK"(港股)
        max_results: 返回的最大新闻数，建议范围 5-20，默认 10

    Returns:
        JSON 格式的 ToolResult，包含 status、data、error_code、suggestion 字段
    """
    if not stock_code:
        return format_tool_result(error_result(
            ErrorCodes.MISSING_PARAM,
            "未提供股票代码"
        ))

    try:
        news_list = _fetch_news_data(stock_code, max_results)

        if news_list:
            source = news_list[0].get('source', 'Unknown')
            if "(DB)" in source: source_label = "数据库缓存"
            elif "AKShare" in source: source_label = "AKShare"
            elif "Finnhub" in source: source_label = "Finnhub"
            elif "Google" in source: source_label = "Google News"
            else: source_label = "聚合数据"

            return format_tool_result(success_result(_format_news_list(news_list, source_label)))

        return format_tool_result(no_data_result(
            message=f"未找到 {stock_code} 的新闻数据",
            suggestion="这是正常状态，不要重试或尝试其他参数"
        ))
    except Exception as e:
        logger.error(f"get_stock_news failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            str(e)
        ))


def get_finance_news(
    query: str
) -> str:
    """
    搜索财经新闻。

    Args:
        query: 搜索关键词

    Returns:
        JSON 格式的 ToolResult，包含 status、data、error_code、suggestion 字段
    """
    try:
        data = get_manager().get_finance_news(query=query)
        return format_tool_result(success_result(format_result(data, f"News: {query}")))
    except Exception as e:
        logger.error(f"get_finance_news failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            str(e)
        ))


def get_hot_news_7x24(
    limit: int = 100
) -> str:
    """
    获取 7x24 小时全球财经快讯。

    Args:
        limit: 获取条数，默认 100

    Returns:
        JSON 格式的 ToolResult，包含 status、data、error_code、suggestion 字段
    """
    try:
        data = get_manager().get_hot_news_7x24(limit=limit)
        return format_tool_result(success_result(format_result(data, "Hot News 7x24")))
    except Exception as e:
        logger.error(f"get_hot_news_7x24 failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            str(e)
        ))


def get_current_timestamp(
    format: str = "%Y-%m-%d %H:%M:%S"
) -> str:
    """
    获取当前时间戳。

    Args:
        format: 格式字符串，默认 "%Y-%m-%d %H:%M:%S"

    Returns:
        当前时间戳字符串
    """
    return format_tool_result(success_result(now_utc().strftime(format)))


# --- 元数据 ---

TOOL_FUNCTIONS = [get_stock_news, get_finance_news, get_hot_news_7x24, get_current_timestamp]
DATA_SOURCE_MAP = {
    "get_stock_news": ["tushare", "akshare", "finnhub"],
    "get_finance_news": ["tushare", "akshare"],
    "get_hot_news_7x24": ["tushare", "akshare"],
    "get_current_timestamp": [],
}
ANALYST_MAP = {
    "get_stock_news": ["financial-news-analyst"],
    "get_finance_news": ["financial-news-analyst"],
    "get_hot_news_7x24": ["financial-news-analyst"],
    "get_current_timestamp": ["market-analyst", "financial-news-analyst", "china-market-analyst", "social-media-analyst", "fundamentals-analyst", "short-term-capital-analyst"],
}
