"""
新闻工具 - 股票新闻数据获取
"""
import logging
from datetime import datetime

from app.utils.time_utils import now_utc
from app.engine.tools.common.tool_result import success_result, no_data_result, error_result, format_tool_result, ErrorCodes
from app.core.async_utils import run_async
logger = logging.getLogger(__name__)


def _get_market_for_code(stock_code: str) -> str:
    """根据股票代码判断市场。"""
    try:
        from app.utils.stock_utils import StockUtils
        market_info = StockUtils.get_market_info(stock_code)
        if market_info.get('is_hk'):
            return "HK"
        if market_info.get('is_us'):
            return "US"
    except Exception as e:
        logger.debug(f"市场类型检测失败，默认CN: {e}")
        pass
    return "CN"


def _clean_symbol(stock_code: str) -> str:
    """清理股票代码后缀。"""
    return stock_code.replace('.SH', '').replace('.SZ', '').replace('.SS', '') \
                     .replace('.XSHE', '').replace('.XSHG', '').replace('.HK', '')


def _fetch_news_data(stock_code: str, max_results: int = 10) -> list:
    """内部辅助函数：通过 DataInterface 获取新闻数据列表。"""
    news_list = []
    market = _get_market_for_code(stock_code)
    clean_code = _clean_symbol(stock_code)

    try:
        from app.data.core.interface import DataInterface
        di = DataInterface.get_instance()
        result = run_async(di.read(market, "news", symbol=clean_code))
        data = result.get("data")

        if data and isinstance(data, list):
            for item in data[:max_results]:
                news_list.append({
                    'title': item.get('title', '无标题'),
                    'content': item.get('content', '') or item.get('summary', ''),
                    'source': f"{item.get('data_source', item.get('source', '未知'))} (DB)",
                    'publish_time': item.get('publish_time', now_utc()),
                    'sentiment': item.get('sentiment', 'neutral'),
                    'url': item.get('url', ''),
                })
            if news_list:
                logger.info(f"[新闻工具] 数据库缓存命中: {len(news_list)} 条")
                return news_list
    except Exception as e:
        logger.warning(f"[新闻工具] 通过 DataInterface 获取失败: {e}")

    # 回退：尝试 refresh 并重新读取
    try:
        from app.data.core.interface import DataInterface
        di = DataInterface.get_instance()
        refresh_result = run_async(di.refresh(market, clean_code, domains=["news"], force=True, timeout=30))
        if refresh_result and refresh_result.domains.get("news"):
            result = run_async(di.read(market, "news", symbol=clean_code))
            data = result.get("data")
            if data and isinstance(data, list):
                for item in data[:max_results]:
                    news_list.append({
                        'title': item.get('title', '无标题'),
                        'content': item.get('content', '') or item.get('summary', ''),
                        'source': f"{item.get('data_source', item.get('source', '未知'))} (Refreshed)",
                        'publish_time': item.get('publish_time', now_utc()),
                        'sentiment': item.get('sentiment', 'neutral'),
                        'url': item.get('url', ''),
                    })
                if news_list:
                    return news_list
    except Exception as e:
        logger.warning(f"[新闻工具] 刷新后获取失败: {e}")

    return news_list


def _format_news_list(news_list: list, source_label: str = None) -> str:
    """格式化新闻列表为 Markdown"""
    if not news_list:
        return "暂无新闻数据"

    report = f"# 最新新闻 {'(' + source_label + ')' if source_label else ''}\n\n"
    report += f"查询时间: {now_utc().strftime('%Y-%m-%d %H:%M:%S')}\n"
    report += f"新闻数量: {len(news_list)} 条\n\n"

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

        report += f"## {i}. {title}\n\n"
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
            if "(DB)" in source:
                source_label = "数据库缓存"
            elif "(Refreshed)" in source:
                source_label = "实时刷新"
            else:
                source_label = "聚合数据"

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
