"""Toolkit 新闻类工具 — get_finnhub_news, get_reddit_stock_info,
get_realtime_stock_news, get_stock_news_unified。"""

from datetime import datetime, timedelta
from typing import Annotated

from langchain_core.tools import tool

from app.utils.logging_init import get_logger
from app.utils.tool_logging import log_tool_call

from .toolkit_helpers import _run_async, _get_us_news_sync, _get_stock_info_sync

logger = get_logger("agents")


@tool
def get_finnhub_news(
    ticker: Annotated[str, "Search query of a company, e.g. 'AAPL, TSM, etc."],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
):
    """
    Retrieve the latest news about a given stock from Finnhub within a date range
    Args:
        ticker (str): Ticker of a company. e.g. AAPL, TSM
        start_date (str): Start date in yyyy-mm-dd format
        end_date (str): End date in yyyy-mm-dd format
    Returns:
        str: A formatted dataframe containing news about the company within the date range from start_date to end_date
    """

    end_date = datetime.strptime(end_date, "%Y-%m-%d")
    start_date = datetime.strptime(start_date, "%Y-%m-%d")

    finnhub_news_result = _get_us_news_sync(ticker)

    return finnhub_news_result


@tool
def get_reddit_stock_info(
    ticker: Annotated[str, "Ticker of a company. e.g. AAPL, TSM"],
    curr_date: Annotated[str, "Current date you want to get news for"],
) -> str:
    """
    Retrieve the latest news about a given stock from Reddit, given the current date.
    Args:
        ticker (str): Ticker of a company. e.g. AAPL, TSM
        curr_date (str): current date in yyyy-mm-dd format to get news for
    Returns:
        str: A formatted dataframe containing the latest news about the company on the given date
    """

    stock_news_results = _get_us_news_sync(ticker)

    return stock_news_results


@tool
def get_realtime_stock_news(
    ticker: Annotated[str, "Ticker of a company. e.g. AAPL, TSM"],
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
) -> str:
    """
    获取股票的实时新闻分析，解决传统新闻源的滞后性问题。
    整合多个专业财经API，提供15-30分钟内的最新新闻。
    支持多种新闻源轮询机制，优先使用实时新闻聚合器，失败时自动尝试备用新闻源。
    对于A股和港股，会优先使用中文财经新闻源（如东方财富）。

    Args:
        ticker (str): 股票代码，如 AAPL, TSM, 600036.SH
        curr_date (str): 当前日期，格式为 yyyy-mm-dd
    Returns:
        str: 包含实时新闻分析、紧急程度评估、时效性说明的格式化报告
    """
    try:
        from app.data.core.interface import DataInterface

        di = DataInterface.get_instance()
        market = "CN"
        if ticker and (
            ".HK" in ticker
            or ticker.isdigit()
            and len(ticker) == 5
            and ticker[0] == "0"
        ):
            market = "HK"
        elif ticker and ticker.isalpha() and ticker == ticker.upper():
            market = "US"
        result = _run_async(di.read(market, "news", symbol=ticker))
        news_data = result.get("data", [])
        if not news_data:
            return f"暂无 {ticker} 的实时新闻数据"
        if isinstance(news_data, list):
            items = news_data[:10]
        else:
            items = [news_data]
        report_lines = [f"## {ticker} 实时新闻分析 ({curr_date})\n"]
        for item in items:
            title = item.get("title", "")
            content = item.get("content", item.get("summary", ""))
            source = item.get("source", item.get("data_source", ""))
            pub_time = item.get("publish_time", "")
            report_lines.append(f"- [{source} {pub_time}] {title}")
            if content:
                report_lines.append(f"  {content[:200]}")
        report_lines.append(f"\n数据来源: 统一数据平台 (market={market})")
        return "\n".join(report_lines)
    except Exception as e:
        return f"实时新闻获取失败: {e}"


@tool
@log_tool_call(tool_name="get_stock_news_unified", log_args=True)
def get_stock_news_unified(
    ticker: Annotated[str, "股票代码（支持A股、港股、美股）"],
    curr_date: Annotated[str, "当前日期，格式：YYYY-MM-DD"],
) -> str:
    """
    统一的股票新闻工具
    自动识别股票类型（A股、港股、美股）并调用相应的新闻数据源

    Args:
        ticker: 股票代码（如：000001、0700.HK、AAPL）
        curr_date: 当前日期（格式：YYYY-MM-DD）

    Returns:
        str: 新闻分析报告
    """
    logger.debug(f"📰 [统一新闻工具] 分析股票: {ticker}")

    try:
        from app.utils.stock_utils import StockUtils

        # 自动识别股票类型
        market_info = StockUtils.get_market_info(ticker)
        is_china = market_info["is_china"]
        is_hk = market_info["is_hk"]
        is_us = market_info["is_us"]

        logger.debug(f"📰 [统一新闻工具] 股票类型: {market_info['market_name']}")

        # 计算新闻查询的日期范围
        end_date = datetime.strptime(curr_date, "%Y-%m-%d")
        start_date = end_date - timedelta(days=7)
        start_date_str = start_date.strftime("%Y-%m-%d")

        result_data = []

        if is_china or is_hk:
            # 中国A股和港股：使用AKShare东方财富新闻和Google新闻（中文搜索）
            logger.debug(f"🇨🇳🇭🇰 [统一新闻工具] 处理中文新闻...")

            # 1. 尝试获取AKShare东方财富新闻
            try:
                clean_ticker = (
                    ticker.replace(".SH", "")
                    .replace(".SZ", "")
                    .replace(".SS", "")
                    .replace(".HK", "")
                    .replace(".XSHE", "")
                    .replace(".XSHG", "")
                )

                logger.debug(
                    f"🇨🇳🇭🇰 [统一新闻工具] 尝试获取东方财富新闻: {clean_ticker}"
                )

                try:
                    from app.data.core.interface import DataInterface

                    _di = DataInterface.get_instance()
                    market_code = "CN" if market_info.get("is_china") else "HK"
                    _r = _run_async(_di.read(market_code, "news", symbol=clean_ticker))
                    news_data = _r.get("data", [])
                    if news_data:
                        if isinstance(news_data, list):
                            news_items = news_data
                        else:
                            news_items = [news_data]
                        em_news_items = []
                        for item in news_items:
                            news_title = item.get("title", "") or item.get(
                                "新闻标题", ""
                            )
                            news_time = item.get("publish_time", "") or item.get(
                                "发布时间", ""
                            )
                            news_url = item.get("url", "") or item.get("新闻链接", "")
                            news_item = (
                                f"- **{news_title}** [{news_time}]({news_url})"
                            )
                            em_news_items.append(news_item)
                        if em_news_items:
                            em_news_text = "\n".join(em_news_items)
                            result_data.append(
                                f"## 东方财富新闻\n{em_news_text}"
                            )
                            logger.debug(
                                f"🇨🇳🇭🇰 [统一新闻工具] 成功获取{len(em_news_items)}条东方财富新闻"
                            )
                    else:
                        result_data.append("## 东方财富新闻\n暂无新闻数据")
                except Exception as inner_e:
                    logger.error(
                        f"❌ [统一新闻工具] 东方财富新闻获取失败: {inner_e}"
                    )
                    result_data.append(f"## 东方财富新闻\n获取失败: {inner_e}")
            except Exception as em_e:
                logger.error(f"❌ [统一新闻工具] 东方财富新闻获取失败: {em_e}")
                result_data.append(f"## 东方财富新闻\n获取失败: {em_e}")

            # 2. 获取Google新闻作为补充
            try:
                if is_china:
                    clean_ticker = (
                        ticker.replace(".SH", "")
                        .replace(".SZ", "")
                        .replace(".SS", "")
                        .replace(".XSHE", "")
                        .replace(".XSHG", "")
                    )
                    search_query = f"{clean_ticker} 股票 公司 财报 新闻"
                    logger.debug(
                        f"🇨🇳 [统一新闻工具] A股Google新闻搜索关键词: {search_query}"
                    )
                else:
                    search_query = f"{ticker} 港股"
                    logger.debug(
                        f"🇭🇰 [统一新闻工具] 港股Google新闻搜索关键词: {search_query}"
                    )

                from app.data.core.interface import DataInterface

                _di = DataInterface.get_instance()
                market_code = "CN" if market_info.get("is_china") else "HK"
                _r = _run_async(_di.read(market_code, "news", symbol=ticker))
                news_data = _r.get("data")
                result_data.append(f"## Google新闻\n{news_data}")
                logger.debug(f"🇨🇳🇭🇰 [统一新闻工具] 成功获取Google新闻")
            except Exception as google_e:
                logger.error(f"❌ [统一新闻工具] Google新闻获取失败: {google_e}")
                result_data.append(f"## Google新闻\n获取失败: {google_e}")

        else:
            # 美股：使用Finnhub新闻
            logger.debug(f"🇺🇸 [统一新闻工具] 处理美股新闻...")

            try:
                from app.data.core.interface import DataInterface

                _di = DataInterface.get_instance()
                _r = _run_async(_di.read("US", "news", symbol=ticker.upper()))
                news_data = _r.get("data")
                result_data.append(f"## 美股新闻\n{news_data}")
            except Exception as e:
                result_data.append(f"## 美股新闻\n获取失败: {e}")

        # 组合所有数据
        combined_result = f"""# {ticker} 新闻分析

**股票类型**: {market_info['market_name']}
**分析日期**: {curr_date}
**新闻时间范围**: {start_date_str} 至 {curr_date}

{chr(10).join(result_data)}

---
*数据来源: 根据股票类型自动选择最适合的新闻源*
"""

        logger.debug(
            f"📰 [统一新闻工具] 数据获取完成，总长度: {len(combined_result)}"
        )
        return combined_result

    except Exception as e:
        error_msg = f"统一新闻工具执行失败: {str(e)}"
        logger.error(f"❌ [统一新闻工具] {error_msg}")
        return error_msg
