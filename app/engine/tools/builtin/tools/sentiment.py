"""
情绪分析工具 - 股票市场情绪分析数据
"""
import logging
from datetime import datetime

from app.utils.time_utils import now_utc, get_current_date
from app.engine.tools.common.tool_result import success_result, no_data_result, error_result, format_tool_result, ErrorCodes
from app.core.async_utils import run_async
logger = logging.getLogger(__name__)


def get_stock_sentiment(
    stock_code: str,
    current_date: str,
) -> str:
    """
    获取股票新闻情绪统计。

    统计近期新闻的情感标签分布（正面/负面/中性），计算情绪评分。
    注意：此工具基于新闻数据中已有的 sentiment 字段进行统计，不执行实时NLP分析。

    Args:
        stock_code: 股票代码，如 "000001.SZ"(A股)、"AAPL"(美股)、"00700.HK"(港股)
        current_date: 当前日期，格式 YYYY-MM-DD

    Returns:
        JSON 格式的 ToolResult
    """
    logger.info(f"[新闻情绪统计] 分析股票: {stock_code}")
    start_time = now_utc()

    try:
        from app.utils.stock_utils import StockUtils

        market_info = StockUtils.get_market_info(stock_code)
        is_china = market_info['is_china']
        is_hk = market_info['is_hk']
        is_us = market_info['is_us']

        result_data = []

        if is_china or is_hk:
            from app.engine.tools.builtin.tools.news import _fetch_news_data
            news_list = _fetch_news_data(stock_code, 20)

            if news_list:
                positive = 0
                negative = 0
                neutral = 0

                for news in news_list:
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
                result_data.append("## 社交媒体情绪\n暂无新闻数据用于情绪分析")

        else:
            try:
                from app.data.core.interface import DataInterface
                _di = DataInterface.get_instance()
                _r = run_async(_di.read("US", "news", symbol=stock_code.upper()))
                reddit_info = _r.get("data")
                if reddit_info:
                    result_data.append(f"## Reddit讨论\n{reddit_info}")
            except Exception:
                pass

            if not result_data:
                result_data.append("## 市场情绪分析\n暂无数据")

        execution_time = (now_utc() - start_time).total_seconds()

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
