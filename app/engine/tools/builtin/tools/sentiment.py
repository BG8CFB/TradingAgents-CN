"""
情绪分析工具 - 股票市场情绪分析数据
"""
import json
import logging
from typing import Optional
from datetime import datetime, timedelta

from app.utils.time_utils import now_utc, get_current_date, get_current_date_compact
from app.engine.tools.builtin.standard import success_result, no_data_result, error_result, format_tool_result, ErrorCodes
from app.engine.tools.builtin.helpers import get_manager, format_result

logger = logging.getLogger(__name__)


def get_stock_sentiment(
    stock_code: str,
    current_date: str,
    start_date: str = None,
    end_date: str = None,
    source_name: str = None
) -> str:
    """
    获取股票市场情绪分析数据。

    返回包括投资者情绪指数、社交媒体热度、内部人士交易信号等。

    Args:
        stock_code: 股票代码，如 "000001.SZ"(A股)、"AAPL"(美股)、"00700.HK"(港股)
        current_date: 当前日期，格式 YYYY-MM-DD
        start_date: 保留参数，暂未使用
        end_date: 保留参数，暂未使用
        source_name: 保留参数，暂未使用

    Returns:
        JSON 格式的 ToolResult，包含 status、data、error_code、suggestion 字段
    """
    # 参数保留用于未来扩展，当前未使用
    _ = start_date, end_date, source_name
    logger.info(f"😊 [MCP情绪工具] 分析股票: {stock_code}")
    start_time = now_utc()

    try:
        from app.utils.stock_utils import StockUtils

        # 自动识别股票类型
        market_info = StockUtils.get_market_info(stock_code)
        is_china = market_info['is_china']
        is_hk = market_info['is_hk']
        is_us = market_info['is_us']

        logger.info(f"😊 [MCP情绪工具] 股票类型: {market_info['market_name']}")

        result_data = []

        if is_china or is_hk:
            # 中国A股和港股：使用社交媒体情绪分析
            logger.info(f"🇨🇳🇭🇰 [MCP情绪工具] 处理中文市场情绪...")

            # 1. 获取新闻数据 (复用 _fetch_news_data 的逻辑)
            from app.engine.tools.builtin.tools.news import _fetch_news_data
            news_list = _fetch_news_data(stock_code, 20)

            if news_list:
                # 简单计算情绪分数
                positive = 0
                negative = 0
                neutral = 0

                for news in news_list:
                    # 如果新闻项本身带有 sentiment 字段（AKShareProvider/TushareProvider 返回的）
                    s = news.get('sentiment', 'neutral')
                    if s == 'positive': positive += 1
                    elif s == 'negative': negative += 1
                    else: neutral += 1

                total = positive + negative + neutral
                score = (positive - negative) / total if total > 0 else 0

                sentiment_summary = f"""
## 中文市场情绪分析

**股票**: {stock_code} ({market_info['market_name']})
**分析日期**: {current_date}
**分析周期**: 近期新闻

📊 综合情绪评估:
市场情绪: {'乐观' if score > 0.2 else '悲观' if score < -0.2 else '中性'} (评分: {score:.2f}, 置信度: {'高' if total > 10 else '低'})

📰 财经新闻情绪:
- 情绪评分: {score:.2f}
- 正面: {positive} 条
- 负面: {negative} 条
- 中性: {neutral} 条
- 数据来源: {news_list[0].get('source', 'Unknown')} 等

"""
                result_data.append(sentiment_summary)
            else:
                logger.warning(f"⚠️ [MCP情绪工具] 中文情绪数据为空，尝试备用源")
                # 备用：Reddit新闻
                try:
                    from app.data.interface import get_reddit_company_news
                    reddit_data = get_reddit_company_news(stock_code, current_date, 7, 5)
                    if reddit_data:
                        result_data.append(f"## Reddit讨论(备用)\n{reddit_data}")
                except Exception as e:
                    result_data.append(f"## 社交媒体情绪\n⚠️ 数据获取失败: {e}")

        else:
            # 美股：使用Finnhub内幕交易和情绪数据
            logger.info(f"🇺🇸 [MCP情绪工具] 处理美股市场情绪...")

            try:
                # 尝试获取内幕交易情绪
                try:
                    from app.data.interface import get_finnhub_company_insider_sentiment

                    insider_sentiment = get_finnhub_company_insider_sentiment(stock_code, current_date, 30)
                    if insider_sentiment:
                        result_data.append(f"## 内部人士情绪\n{insider_sentiment}")
                except Exception as e:
                    logger.warning(f"⚠️ [MCP情绪工具] 内幕交易数据获取失败: {e}")

                # 尝试获取Reddit讨论
                try:
                    from app.data.interface import get_reddit_company_news
                    reddit_info = get_reddit_company_news(stock_code, current_date, 7, 5)
                    if reddit_info:
                        result_data.append(f"## Reddit讨论\n{reddit_info}")
                except Exception as e:
                    logger.warning(f"⚠️ [MCP情绪工具] Reddit数据获取失败: {e}")

                if not result_data:
                    result_data.append("## 市场情绪分析\n暂无数据")

            except Exception as e:
                logger.error(f"❌ [MCP情绪工具] 美股情绪获取失败: {e}")
                result_data.append(f"## 市场情绪分析\n暂无数据 (数据源访问异常)")

        # 计算执行时间
        execution_time = (now_utc() - start_time).total_seconds()

        # 组合所有数据
        combined_result = f"""# {stock_code} 市场情绪分析

**股票类型**: {market_info['market_name']}
**分析日期**: {current_date}
**执行时间**: {execution_time:.2f}秒

{chr(10).join(result_data)}

---
*数据来源: 社交媒体、新闻评论及内部交易数据*
"""
        return format_tool_result(success_result(combined_result))

    except Exception as e:
        logger.error(f"get_stock_sentiment failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            str(e)
        ))


# --- 元数据 ---

TOOL_FUNCTIONS = [get_stock_sentiment]
DATA_SOURCE_MAP = {
    "get_stock_sentiment": ["tushare", "akshare", "finnhub"],
}
ANALYST_MAP = {
    "get_stock_sentiment": ["social-media-analyst"],
}
