"""
MCP Finance Tools

Implements the 17 finance tools defined in FinanceMCP_Tools_Reference.md.

并发安全：使用线程本地存储，每个线程有独立的 DataSourceManager 实例
"""
import logging
import json
import re
import threading
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from app.data.manager import DataSourceManager
from app.utils.time_utils import now_utc, get_current_date, get_current_date_compact
from .tool_standard import success_result, no_data_result, error_result, format_tool_result, ErrorCodes

logger = logging.getLogger(__name__)

# 线程本地存储，每个线程有独立的 manager 实例
_thread_local = threading.local()

def get_manager() -> DataSourceManager:
    """获取当前线程的 DataSourceManager 实例（线程安全）"""
    if not hasattr(_thread_local, 'manager'):
        _thread_local.manager = DataSourceManager()
        logger.debug(f"创建新的 DataSourceManager 实例 (线程: {threading.current_thread().name})")
    return _thread_local.manager

# 向后兼容的全局引用（实际上调用线程安全版本）
def _get_global_manager():
    """向后兼容：获取全局 manager（已废弃，建议使用 get_manager()）"""
    return get_manager()

# --- 1. Stock Data ---

def get_stock_data(
    stock_code: str,
    market_type: str = "cn",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    indicators: Optional[str] = None
) -> str:
    """
    获取股票行情数据及技术指标。

    返回开盘价、最高价、最低价、收盘价、成交量等行情数据，以及可选的技术指标。

    Args:
        stock_code: 股票代码，如 "000001.SZ"(A股)、"AAPL"(美股)、"00700.HK"(港股)
        market_type: 市场类型: "cn"(A股)、"us"(美股)、"hk"(港股)，默认自动推断
        start_date: 开始日期，格式 YYYY-MM-DD 或 YYYYMMDD，默认 1 个月前
        end_date: 结束日期，格式 YYYY-MM-DD 或 YYYYMMDD，默认今天
        indicators: 技术指标表达式，如 "macd(12,26,9) rsi(14)"

    Returns:
        JSON 格式的 ToolResult，包含 status、data、error_code、suggestion 字段
    """
    try:
        from app.utils.stock_utils import StockUtils

        # 1. 自动推断市场类型 (优先使用 StockUtils)
        market_info = StockUtils.get_market_info(stock_code)
        is_china = market_info['is_china']
        is_hk = market_info['is_hk']
        is_us = market_info['is_us']

        # 如果无法识别，回退到参数指定
        if not (is_china or is_hk or is_us):
            if market_type == "hk": is_hk = True
            elif market_type == "us": is_us = True
            else: is_china = True

        # 2. 设置默认日期
        if not start_date:
            start_date = (now_utc() - timedelta(days=30)).strftime('%Y-%m-%d')
        if not end_date:
            end_date = get_current_date()

        # 3. 调用统一数据接口 (包含 Write-Through 逻辑)
        data = None
        market_name = ""

        if is_china:
            from app.data.interface import get_china_stock_data_unified
            data = get_china_stock_data_unified(stock_code, start_date, end_date)
            market_name = "A股"

        elif is_hk:
            from app.data.interface import get_hk_stock_data_unified
            data = get_hk_stock_data_unified(stock_code, start_date, end_date)
            market_name = "港股"

        elif is_us:
            data = get_manager().get_stock_data(stock_code, "us", start_date, end_date)
            market_name = "美股"

        # 返回 JSON 格式
        if data is not None:
            # data 可能是 DataFrame 或字符串
            import pandas as pd
            if isinstance(data, pd.DataFrame):
                # 转换为 JSON 字符串
                json_data = data.to_dict(orient='records')
                import json
                data_str = json.dumps(json_data, ensure_ascii=False, default=str)
            else:
                # 已经是字符串格式
                data_str = str(data)

            return format_tool_result(success_result(
                data=data_str,
                message=f"{market_name}行情数据 ({stock_code})"
            ))
        else:
            return format_tool_result(error_result(
                ErrorCodes.UNKNOWN_MARKET,
                f"无法识别股票代码 {stock_code} 的市场类型",
                suggestion="请使用标准格式的股票代码，如 000001.SZ、00700.HK、AAPL"
            ))

    except Exception as e:
        logger.error(f"get_stock_data failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            f"获取股票数据失败: {str(e)}"
        ))

# --- 1.1 Unified Stock News ---

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

def get_stock_fundamentals(
    stock_code: str,
    current_date: str = None,
    start_date: str = None,
    end_date: str = None
) -> str:
    """
    获取股票基本面财务数据和估值指标。

    返回包括财务报表、估值指标、盈利能力等基本面数据。

    Args:
        stock_code: 股票代码，如 "000001.SZ"(A股)、"AAPL"(美股)、"00700.HK"(港股)
        current_date: 当前日期，格式 YYYY-MM-DD，默认今天
        start_date: 开始日期，格式 YYYY-MM-DD，默认 10 天前
        end_date: 结束日期，格式 YYYY-MM-DD，默认今天

    Returns:
        JSON 格式的 ToolResult，包含 status、data、error_code、suggestion 字段
    """
    logger.info(f"📊 [MCP基本面工具] 分析股票: {stock_code}")
    start_time = now_utc()

    # 设置默认日期
    if not current_date:
        current_date = get_current_date()

    if not start_date:
        start_date = (now_utc() - timedelta(days=10)).strftime('%Y-%m-%d')

    if not end_date:
        end_date = current_date

    # 分级分析已废弃，统一使用标准深度
    data_depth = "standard"

    try:
        from app.utils.stock_utils import StockUtils

        # 自动识别股票类型
        market_info = StockUtils.get_market_info(stock_code)
        is_china = market_info['is_china']
        is_hk = market_info['is_hk']
        is_us = market_info['is_us']

        logger.info(f"📊 [MCP基本面工具] 股票类型: {market_info['market_name']}")

        result_data = []

        if is_china:
            # 中国A股
            logger.info(f"🇨🇳 [MCP基本面工具] 处理A股数据...")

            # 获取最新股价信息 (仅用于辅助分析，不直接返回)
            current_price_data = ""
            try:
                recent_end_date = current_date
                recent_start_date = (datetime.strptime(current_date, '%Y-%m-%d') - timedelta(days=2)).strftime('%Y-%m-%d')

                from app.data.interface import get_china_stock_data_unified
                current_price_data = get_china_stock_data_unified(stock_code, recent_start_date, recent_end_date)
            except Exception as e:
                logger.error(f"❌ [MCP基本面工具] A股价格数据获取失败: {e}")
                current_price_data = ""

            # 获取基本面财务数据
            try:
                from app.data.providers.china.optimized import OptimizedChinaDataProvider
                analyzer = OptimizedChinaDataProvider()

                # 根据数据深度选择分析模块
                analysis_modules = data_depth

                # 尝试调用报告生成方法
                if hasattr(analyzer, "generate_fundamentals_report"):
                    fundamentals_data = analyzer.generate_fundamentals_report(stock_code, current_price_data, analysis_modules)
                elif hasattr(analyzer, "_generate_fundamentals_report"):
                    fundamentals_data = analyzer._generate_fundamentals_report(stock_code, current_price_data, analysis_modules)
                else:
                    fundamentals_data = "基本面报告生成方法不可用"

                result_data.append(f"## A股基本面财务数据\n{fundamentals_data}")
            except Exception as e:
                logger.error(f"❌ [MCP基本面工具] A股基本面数据获取失败: {e}")
                result_data.append(f"## A股基本面财务数据\n⚠️ 获取失败: {e}")

        elif is_hk:
            # 港股
            logger.info(f"🇭🇰 [MCP基本面工具] 处理港股数据...")

            # 1. 获取基础信息
            try:
                from app.data.interface import get_hk_stock_info_unified
                hk_info = get_hk_stock_info_unified(stock_code)

                basic_info = f'''## 港股基础信息
**名称**: {hk_info.get('name', 'N/A')}
**行业**: {hk_info.get('industry', 'N/A')}
**市值**: {hk_info.get('market_cap', 'N/A')}
**市盈率(PE)**: {hk_info.get('pe', 'N/A')}
**周息率**: {hk_info.get('dividend_yield', 'N/A')}%
'''
                result_data.append(basic_info)
            except Exception as e:
                logger.error(f"❌ [MCP基本面工具] 港股基础信息获取失败: {e}")
                result_data.append(f"## 港股基础信息\n⚠️ 获取失败: {e}")

        else:
            # 美股
            logger.info(f"🇺🇸 [MCP基本面工具] 处理美股数据...")
            try:
                # 尝试使用 Finnhub 获取基本面
                try:
                    from app.data.interface import get_us_stock_info
                    us_info = get_us_stock_info(stock_code)
                    if us_info:
                        result_data.append(f"## 美股基本面信息\n{us_info}")
                    else:
                        result_data.append(f"## 美股基本面信息\n暂无详细数据")
                except ImportError:
                     result_data.append(f"## 美股基本面信息\n⚠️ 接口不可用")
            except Exception as e:
                logger.error(f"❌ [MCP基本面工具] 美股数据获取失败: {e}")
                result_data.append(f"## 美股基本面信息\n⚠️ 获取失败: {e}")

        # 计算执行时间
        execution_time = (now_utc() - start_time).total_seconds()

        # 组合所有数据
        combined_result = f"""# {stock_code} 基本面分析

**股票类型**: {market_info['market_name']}
**分析日期**: {current_date}
**执行时间**: {execution_time:.2f}秒

{chr(10).join(result_data)}
"""
        return format_tool_result(success_result(combined_result))

    except Exception as e:
        logger.error(f"get_stock_fundamentals failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            str(e)
        ))

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

            # 1. 获取新闻数据 (复用 get_stock_news 的逻辑)
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

def get_china_market_overview(
    date: str = None,
    include_indices: bool = True,
    include_sectors: bool = True
) -> str:
    """
    获取中国A股市场整体概览。

    返回市场指数、板块表现、资金流向等宏观市场数据。

    Args:
        date: 查询日期，格式 YYYY-MM-DD，默认今天
        include_indices: 是否包含主要指数数据（上证、深证、创业板等）
        include_sectors: 是否包含板块表现数据

    Returns:
        JSON 格式的 ToolResult，包含 status、data、error_code、suggestion 字段
    """
    logger.info(f"🇨🇳 [MCP中国市场工具] 获取市场概览")
    start_time = now_utc()

    if not date:
        date = get_current_date()

    result_sections = []

    # 获取主要指数数据
    if include_indices:
        indices_data = []
        indices_source = "Unknown"

        # 定义关注的指数
        indices_to_fetch = [
            ('000001.SH', 'sh000001', '上证指数'),
            ('399001.SZ', 'sz399001', '深证成指'),
            ('399006.SZ', 'sz399006', '创业板指')
        ]

        # 1. 尝试使用 get_manager().get_index_data (支持 DB -> Tushare -> AKShare)
        try:
            for ts_code, ak_code, name in indices_to_fetch:
                # 优先尝试 Tushare 格式代码
                try:
                    # 使用 DataSourceManager 的逻辑
                    index_result = get_manager().get_index_data(code=ts_code, start_date=date, end_date=date)

                    # 简单解析返回的 Markdown 表格获取收盘价
                    if index_result and "|" in index_result:
                        lines = index_result.split('\n')
                        # 寻找包含日期的行
                        data_line = None
                        for line in lines:
                            if date.replace('-', '') in line or date in line:
                                data_line = line
                                break

                        if data_line:
                            indices_data.append(f"- **{name}**: (已获取，请查看详细指数数据)")
                            continue
                except Exception:
                    pass

                # 如果上面失败，尝试 AKShare 直接调用 (作为备用)
                try:
                    import akshare as ak
                    df = ak.stock_zh_index_daily(symbol=ak_code)
                    if not df.empty:
                        latest = df.iloc[-1]
                        close = latest.get('close', 'N/A')
                        indices_data.append(f"- **{name}**: {close}")
                        indices_source = "AKShare"
                except Exception as e:
                    logger.warning(f"获取 {name} 失败: {e}")

        except Exception as e:
            logger.warning(f"获取指数数据异常: {e}")

        if indices_data:
            result_sections.append(f"## 主要指数\n\n" + "\n".join(indices_data))
        else:
            result_sections.append("## 主要指数\n\n⚠️ 指数数据暂时无法获取")

    # 获取板块表现 (AKShare)
    if include_sectors:
        try:
            import akshare as ak
            import concurrent.futures

            # 使用线程池和超时机制执行 AKShare 调用，防止阻塞
            def fetch_sector_data():
                # 直接调用，异常由 future.result() 抛出并在主线程捕获
                return ak.stock_board_industry_name_em()

            sector_df = None
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(fetch_sector_data)
                    sector_df = future.result(timeout=15)  # 15秒超时
            except concurrent.futures.TimeoutError:
                logger.warning("AKShare 板块数据获取超时 (15s)")
                result_sections.append("## 板块表现\n\n⚠️ 数据获取超时，请稍后重试")
            except Exception as e:
                logger.warning(f"AKShare 板块数据获取异常: {e}")
                result_sections.append(f"## 板块表现\n\n⚠️ 数据源异常: {e}")

            if sector_df is not None and not sector_df.empty:
                # 取涨幅前5和跌幅前5
                top_sectors = sector_df.head(5)
                bottom_sectors = sector_df.tail(5)

                sector_info = "## 板块表现 (AKShare)\n\n"
                sector_info += "### 涨幅前5\n"
                for _, row in top_sectors.iterrows():
                    name = row.get('板块名称', 'N/A')
                    change = row.get('涨跌幅', 'N/A')
                    sector_info += f"- {name}: {change}%\n"

                sector_info += "\n### 跌幅前5\n"
                for _, row in bottom_sectors.iterrows():
                    name = row.get('板块名称', 'N/A')
                    change = row.get('涨跌幅', 'N/A')
                    sector_info += f"- {name}: {change}%\n"

                result_sections.append(sector_info)
            elif sector_df is None:
                # 错误信息已在上面添加
                pass
            else:
                result_sections.append("## 板块表现\n\n⚠️ 板块数据暂时无法获取 (空数据)")

        except Exception as e:
            logger.error(f"❌ [MCP中国市场工具] 获取板块数据失败: {e}")
            result_sections.append(f"## 板块表现\n\n⚠️ 获取失败: {e}")

    # 计算执行时间
    execution_time = (now_utc() - start_time).total_seconds()

    # 组合结果
    combined_result = f"""# 中国A股市场概览

**查询日期**: {date}
**执行时间**: {execution_time:.2f}秒

{chr(10).join(result_sections)}

---
*数据来源: AKShare/Tushare*
"""
    logger.info(f"🇨🇳 [MCP中国市场工具] 数据获取完成，总长度: {len(combined_result)}")
    return format_tool_result(success_result(combined_result))

def get_stock_data_minutes(
    market_type: str,
    stock_code: str,
    start_datetime: Optional[str] = None,
    end_datetime: Optional[str] = None,
    freq: str = "30min"
) -> str:
    """
    获取分钟级 K 线数据。

    Args:
        market_type: 市场类型，目前仅支持 "cn"
        stock_code: 股票代码，如 "600519.SH"
        start_datetime: 开始时间，格式 YYYY-MM-DD HH:mm:ss 或 YYYYMMDDHHmmss，默认 1 天前
        end_datetime: 结束时间，格式 YYYY-MM-DD HH:mm:ss 或 YYYYMMDDHHmmss，默认现在
        freq: 频率，支持 "1min"、"5min"、"15min"、"30min"、"60min"，默认 "30min"

    Returns:
        JSON 格式的 ToolResult，包含 status、data、error_code、suggestion 字段
    """
    try:
        # 设置默认时间
        if not end_datetime:
            end_datetime = now_utc().strftime('%Y-%m-%d %H:%M:%S')
        if not start_datetime:
            start_datetime = (now_utc() - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')

        # 🔥 优先使用Tushare获取分钟级行情数据
        try:
            logger.info(f"📊 尝试使用Tushare获取分钟级行情: {stock_code}, 频率: {freq}")
            data = get_manager().get_stock_data_minutes(
                market_type=market_type,
                code=stock_code,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                freq=freq
            )
            if data and not data.empty:
                logger.info(f"✅ Tushare成功获取分钟级行情: {stock_code}, {len(data)}条记录")
                return format_tool_result(success_result(_format_result(data, f"{stock_code} {freq} Data")))
        except Exception as tu_e:
            logger.info(f"⚠️ Tushare获取分钟级行情失败: {tu_e}，尝试AkShare")

        # 回退到AkShare
        if market_type == "cn":
            try:
                import akshare as ak
                import pandas as pd

                # 频率映射
                freq_map = {
                    "1min": "1",
                    "5min": "5",
                    "15min": "15",
                    "30min": "30",
                    "60min": "60"
                }
                period = freq_map.get(freq, "30")

                # 标准化股票代码为6位
                code_6digit = stock_code.replace('.SH', '').replace('.SZ', '').replace('.sh', '').replace('.sz', '').zfill(6)

                logger.info(f"📊 尝试使用AkShare获取分钟级行情: {stock_code}, 频率: {freq}")

                # 获取分钟级数据
                df = ak.stock_zh_a_hist_min_em(symbol=code_6digit, period=period, adjust="")

                if df is not None and not df.empty:
                    logger.info(f"✅ AkShare成功获取分钟级行情: {stock_code}, {len(df)}条记录")

                    # 格式化数据
                    result_text = f"# {stock_code} 分钟级行情（来源：AkShare）\n\n"
                    result_text += f"**频率**: {freq}\n"
                    result_text += f"**记录数**: {len(df)}\n"
                    result_text += f"**时间范围**: {df.iloc[0]['时间']} 至 {df.iloc[-1]['时间']}\n\n"

                    result_text += "## 行情明细（前50条）\n\n"
                    for idx, row in df.head(50).iterrows():
                        result_text += f"### {row['时间']}\n"
                        result_text += f"- **开盘**: {row['开盘']}\n"
                        result_text += f"- **收盘**: {row['收盘']}\n"
                        result_text += f"- **最高**: {row['最高']}\n"
                        result_text += f"- **最低**: {row['最低']}\n"
                        result_text += f"- **成交量**: {row['成交量']}\n"
                        result_text += f"- **成交额**: {row['成交额']}\n"
                        result_text += f"- **涨跌幅**: {row['涨跌幅']}\n"
                        result_text += f"- **涨跌额**: {row['涨跌额']}\n"
                        result_text += f"- **振幅**: {row['振幅']}\n\n"

                    return result_text
                else:
                    logger.warning(f"⚠️ AkShare未获取到分钟级行情数据")
            except Exception as ak_e:
                logger.warning(f"⚠️ AkShare获取分钟级行情失败: {ak_e}")

        # 两个数据源都失败
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            f"无法从Tushare和AkShare获取分钟级行情数据: {stock_code}"
        ))
    except Exception as e:
        logger.error(f"get_stock_data_minutes failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            str(e)
        ))

# --- 2. Company Performance ---

def get_company_performance(
    stock_code: str,
    data_type: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    period: Optional[str] = None
) -> str:
    """
    [已废弃] 请使用 get_company_performance_unified() 代替

    .. deprecated::
        1.1.0
        此函数已被 get_company_performance_unified() 替代
        将在 v1.3.0 版本中移除。请使用新函数：
        get_company_performance_unified("000001.SZ", "forecast", ...)

    获取 A 股公司业绩和财务数据。

    Args:
        stock_code: 股票代码，如 "000001.SZ"
        data_type: 数据类型，支持 forecast(业绩预告)、express(业绩快报)、indicators(财务指标)、dividend(分红送转)等
        start_date: 开始日期，格式 YYYYMMDD，默认 1 年前
        end_date: 结束日期，格式 YYYYMMDD，默认今天
        period: 报告期，格式 YYYYMMDD，可选

    Returns:
        JSON 格式的 ToolResult，包含 status、data、error_code、suggestion 字段
    """
    try:
        # 设置默认日期
        if not end_date:
            end_date = get_current_date_compact()
        if not start_date:
            start_date = (now_utc() - timedelta(days=360)).strftime('%Y%m%d')

        # 🔥 优先使用Tushare获取业绩数据
        try:
            logger.info(f"📊 尝试使用Tushare获取业绩数据: {stock_code}, data_type: {data_type}")
            data = get_manager().get_company_performance(
                stock_code=stock_code,
                data_type=data_type,
                start_date=start_date,
                end_date=end_date,
                period=period
            )
            if data and not data.empty:
                logger.info(f"✅ Tushare成功获取业绩数据: {stock_code}, {len(data)}条记录")
                return format_tool_result(success_result(_format_result(data, f"{stock_code} Performance ({data_type})")))
        except Exception as tu_e:
            logger.info(f"⚠️ Tushare获取业绩数据失败: {tu_e}，尝试AkShare")

        # 回退到AkShare（仅支持业绩预告forecast）
        if data_type == "forecast":
            try:
                import akshare as ak
                import pandas as pd

                # 标准化股票代码为6位
                code_6digit = stock_code.replace('.SH', '').replace('.SZ', '').replace('.sh', '').replace('.sz', '').zfill(6)

                logger.info(f"📊 尝试使用AkShare获取业绩预告: {stock_code}")

                # 获取业绩预告数据
                df = ak.stock_profit_forecast_em()

                if df is not None and not df.empty:
                    # 过滤指定股票的数据
                    df_filtered = df[df['代码'] == code_6digit]

                    if not df_filtered.empty:
                        logger.info(f"✅ AkShare成功获取业绩预告数据: {stock_code}")

                        # 格式化数据
                        result_text = f"# {stock_code} 业绩预告数据（来源：AkShare-东方财富）\n\n"

                        for idx, row in df_filtered.iterrows():
                            result_text += f"## {row.get('名称', stock_code)}\n\n"
                            result_text += f"**股票代码**: {row.get('代码', stock_code)}\n"
                            result_text += f"**研报数**: {row.get('研报数', 'N/A')}\n\n"

                            result_text += "### 机构投资评级（近六个月）\n"
                            result_text += f"- **买入**: {row.get('机构投资评级(近六个月)-买入', 'N/A')}\n"
                            result_text += f"- **增持**: {row.get('机构投资评级(近六个月)-增持', 'N/A')}\n"
                            result_text += f"- **中性**: {row.get('机构投资评级(近六个月)-中性', 'N/A')}\n"
                            result_text += f"- **减持**: {row.get('机构投资评级(近六个月)-减持', 'N/A')}\n"
                            result_text += f"- **卖出**: {row.get('机构投资评级(近六个月)-卖出', 'N/A')}\n\n"

                            result_text += "### 预测每股收益\n"
                            for year in ['2024', '2025', '2026', '2027']:
                                eps_key = f"{year}预测每股收益"
                                if eps_key in row and pd.notna(row[eps_key]):
                                    result_text += f"- **{year}年**: {row[eps_key]:.2f}元\n"

                            result_text += "\n"

                        return result_text
                    else:
                        logger.warning(f"⚠️ AkShare未找到{stock_code}的业绩预告数据")
                else:
                    logger.warning(f"⚠️ AkShare业绩预告接口返回空数据")
            except Exception as ak_e:
                logger.warning(f"⚠️ AkShare获取业绩预告失败: {ak_e}")

        # 两个数据源都失败
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            f"无法从Tushare和AkShare获取业绩数据: {stock_code}, data_type: {data_type}"
        ))
    except Exception as e:
        logger.error(f"get_company_performance failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            str(e)
        ))

def get_company_performance_hk(
    stock_code: str,
    data_type: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    period: Optional[str] = None,
    ind_name: Optional[str] = None
) -> str:
    """
    [已废弃] 请使用 get_company_performance_unified() 代替

    .. deprecated::
        1.1.0
        此函数已被 get_company_performance_unified() 替代
        将在 v1.3.0 版本中移除。请使用新函数：
        get_company_performance_unified("00700.HK", "income", ind_name="净利润", ...)

    获取港股财务数据。

    Args:
        stock_code: 港股代码，如 "00700.HK"
        data_type: 数据类型，支持 income(利润表)、balance(资产负债表)、cashflow(现金流量表)
        start_date: 开始日期，格式 YYYYMMDD，默认 1 年前
        end_date: 结束日期，格式 YYYYMMDD，默认今天
        period: 报告期，可选
        ind_name: 指标名称过滤，可选

    Returns:
        JSON 格式的 ToolResult，包含 status、data、error_code、suggestion 字段
    """
    try:
        # 设置默认日期
        if not end_date:
            end_date = get_current_date_compact()
        if not start_date:
            start_date = (now_utc() - timedelta(days=360)).strftime('%Y%m%d')

        # 🔥 优先使用Tushare获取港股数据
        try:
            logger.info(f"📊 尝试使用Tushare获取港股数据: {stock_code}, data_type: {data_type}")
            data = get_manager().get_company_performance(
                ts_code=stock_code,
                data_type=data_type,
                start_date=start_date,
                end_date=end_date,
                period=period,
                ind_name=ind_name,
                market="hk"
            )
            if data and not data.empty:
                logger.info(f"✅ Tushare成功获取港股数据: {stock_code}, {len(data)}条记录")
                return format_tool_result(success_result(_format_result(data, f"{stock_code} {data_type} (HK)")))
        except Exception as tu_e:
            logger.info(f"⚠️ Tushare获取港股数据失败: {tu_e}，尝试AkShare")

        # 回退到AkShare（仅支持业绩预告forecast）
        if data_type == "forecast":
            try:
                import akshare as ak
                import pandas as pd

                # 标准化港股代码（移除.HK后缀）
                code_clean = stock_code.replace('.HK', '').replace('.hk', '').zfill(5)

                logger.info(f"📊 尝试使用AkShare获取港股业绩预告: {stock_code}")

                # 获取港股业绩预测
                df = ak.stock_hk_profit_forecast_et(symbol=code_clean)

                if df is not None and not df.empty:
                    logger.info(f"✅ AkShare成功获取港股业绩预告: {stock_code}")

                    # 格式化数据
                    result_text = f"# {stock_code} 港股业绩预告（来源：AkShare-东方财富）\n\n"
                    result_text += f"**记录数**: {len(df)}\n\n"

                    result_text += "## 业绩预告明细\n\n"
                    for idx, row in df.iterrows():
                        result_text += f"### 记录 {idx + 1}\n"
                        for col in df.columns:
                            value = row[col]
                            if pd.notna(value):
                                result_text += f"- **{col}**: {value}\n"
                        result_text += "\n"

                    return result_text
                else:
                    logger.warning(f"⚠️ AkShare未获取到港股业绩预告")
            except Exception as ak_e:
                logger.warning(f"⚠️ AkShare获取港股业绩预告失败: {ak_e}")

        # 两个数据源都失败
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            f"无法从Tushare和AkShare获取港股数据: {stock_code}, data_type: {data_type}"
        ))
    except Exception as e:
        logger.error(f"get_company_performance_hk failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            str(e)
        ))

def get_company_performance_us(
    stock_code: str,
    data_type: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    period: Optional[str] = None
) -> str:
    """
    [已废弃] 请使用 get_company_performance_unified() 代替

    .. deprecated::
        1.1.0
        此函数已被 get_company_performance_unified() 替代
        将在 v1.3.0 版本中移除。请使用新函数：
        get_company_performance_unified("AAPL", "balance", ...)

    获取美股财务数据。

    Args:
        stock_code: 美股代码，如 "AAPL"
        data_type: 数据类型，支持 income(利润表)、balance(资产负债表)、cashflow(现金流量表)、indicator(财务指标)
        start_date: 开始日期，格式 YYYYMMDD，默认 1 年前
        end_date: 结束日期，格式 YYYYMMDD，默认今天
        period: 报告期，可选

    Returns:
        JSON 格式的 ToolResult，包含 status、data、error_code、suggestion 字段
    """
    try:
        # 设置默认日期
        if not end_date:
            end_date = get_current_date_compact()
        if not start_date:
            start_date = (now_utc() - timedelta(days=360)).strftime('%Y%m%d')

        data = get_manager().get_company_performance(
            ts_code=stock_code,
            data_type=data_type,
            start_date=start_date,
            end_date=end_date,
            period=period,
            market="us"
        )
        return format_tool_result(success_result(_format_result(data, f"{stock_code} {data_type} (US)")))
    except Exception as e:
        logger.error(f"get_company_performance_us failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            str(e)
        ))

# --- 3. Macro & Flows ---

def get_company_performance_unified(
    stock_code: str,
    data_type: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    period: Optional[str] = None,
    ind_name: Optional[str] = None
) -> str:
    """
    获取公司业绩数据（支持A股、港股、美股）✨ 统一工具

    自动识别股票市场类型，调用对应的数据源。这是整合后的统一工具，
    替代了原来的 get_company_performance()、get_company_performance_hk()、
    get_company_performance_us() 三个工具。

    ⚠️ 数据源支持范围：

    1. A股和港股：
       - forecast (业绩预告): 支持 Tushare 和 AkShare 双数据源
       - express/indicators/income/balance/cashflow: 仅支持 Tushare

    2. 美股：
       - 所有数据类型: 仅支持 Tushare

    如果未配置 Tushare Token，将只能获取 A股和港股的 forecast 数据。

    Args:
        stock_code: 股票代码，如 "000001.SZ"(A股)、"00700.HK"(港股)、"AAPL"(美股)
        data_type: 数据类型，支持：
                   - forecast: 业绩预告（支持双数据源）
                   - express: 业绩快报（仅Tushare）
                   - indicators: 财务指标（仅Tushare）
                   - income: 利润表（仅Tushare）
                   - balance: 资产负债表（仅Tushare）
                   - cashflow: 现金流量表（仅Tushare）
        start_date: 开始日期，格式 YYYYMMDD 或 YYYY-MM-DD，默认 1 年前
        end_date: 结束日期，格式 YYYYMMDD 或 YYYY-MM-DD，默认今天
        period: 报告期，格式 YYYYMMDD，可选
        ind_name: 指标名称过滤，可选（⚠️ 仅港股有效，A股和美股将忽略此参数）

    Returns:
        JSON 格式的 ToolResult，包含 status、data、error_code、suggestion 字段

    Examples:
        >>> get_company_performance_unified("000001.SZ", "forecast")
        >>> get_company_performance_unified("00700.HK", "income", ind_name="净利润")
        >>> get_company_performance_unified("AAPL", "balance")
    """
    try:
        from app.utils.stock_utils import StockUtils

        # 1. 自动识别市场类型
        market_info = StockUtils.get_market_info(stock_code)

        # 确定市场参数
        if market_info['is_china']:
            market = "cn"
            market_name = "A股"
        elif market_info['is_hk']:
            market = "hk"
            market_name = "港股"
        elif market_info['is_us']:
            market = "us"
            market_name = "美股"
            # ⚠️ 美股忽略 ind_name 参数
            if ind_name:
                logger.warning(f"⚠️ ind_name 参数仅对港股有效，美股 {stock_code} 将忽略此参数")
                ind_name = None
        else:
            return format_tool_result(error_result(
                ErrorCodes.UNKNOWN_MARKET,
                f"无法识别股票代码 {stock_code} 的市场类型，请使用标准格式（如 000001.SZ、00700.HK、AAPL）",
                suggestion="检查股票代码格式是否正确，A股需包含交易所后缀（.SZ/.SH），港股需包含.HK后缀"
            ))

        # 2. 设置默认日期
        if not end_date:
            end_date = get_current_date_compact()
        if not start_date:
            start_date = (now_utc() - timedelta(days=360)).strftime('%Y%m%d')

        logger.info(f"📊 [{market_name}业绩] 获取数据: {stock_code}, data_type: {data_type}, start: {start_date}, end: {end_date}")

        # 2.5. ⚠️ 检查数据源支持范围并给出明确提示
        import os
        tushare_token = os.getenv("TUSHARE_TOKEN")

        if not tushare_token or not tushare_token.strip():
            # 未配置 Tushare 的情况
            can_use_akshare = (data_type == "forecast" and market in ["cn", "hk"])
            if not can_use_akshare:
                # 不能使用 AkShare 回退
                error_msg = f"获取 {market_name}{data_type} 数据需要配置 Tushare"
                suggestion_msg = (
                    f"请配置 TUSHARE_TOKEN 环境变量\n"
                    f"或者仅使用 forecast 类型（A股和港股支持）"
                )
                return format_tool_result(error_result(
                    ErrorCodes.DATA_FETCH_ERROR,
                    error_msg,
                    suggestion=suggestion_msg
                ))
            else:
                # 可以使用 AkShare 回退，给出提示
                logger.info(f"⚠️ 未配置 Tushare，将使用 AkShare 获取 A股/港股 forecast 数据")

        # 3. 🔥 优先使用Tushare获取业绩数据
        try:
            logger.info(f"📊 尝试使用Tushare获取{market_name}业绩数据: {stock_code}, data_type: {data_type}")
            data = get_manager().get_company_performance(
                ts_code=stock_code,
                data_type=data_type,
                start_date=start_date,
                end_date=end_date,
                period=period,
                ind_name=ind_name,  # 仅港股有效
                market=market
            )
            if data and not data.empty:
                logger.info(f"✅ Tushare成功获取{market_name}业绩数据: {stock_code}, {len(data)}条记录")
                return format_tool_result(success_result(_format_result(data, f"{stock_code} Performance ({market.upper()})")))
        except Exception as tu_e:
            logger.info(f"⚠️ Tushare获取{market_name}业绩数据失败: {tu_e}，尝试AkShare")

        # 4. 回退到AkShare（仅支持A股和港股的业绩预告forecast）
        if data_type == "forecast" and market in ["cn", "hk"]:
            try:
                import akshare as ak
                import pandas as pd

                logger.info(f"📊 尝试使用AkShare获取{market_name}业绩预告: {stock_code}")

                if market == "cn":
                    # A股业绩预告
                    code_6digit = stock_code.replace('.SH', '').replace('.SZ', '').replace('.sh', '').replace('.sz', '').zfill(6)
                    df = ak.stock_profit_forecast_em()

                    if df is not None and not df.empty:
                        df_filtered = df[df['代码'] == code_6digit]

                        if not df_filtered.empty:
                            logger.info(f"✅ AkShare成功获取A股业绩预告数据: {stock_code}, {len(df_filtered)}条记录")

                            # 格式化输出
                            result_text = f"# {stock_code} A股业绩预告数据（来源：AkShare-东方财富）\n\n"
                            result_text += _format_result(df_filtered, f"{stock_code} Forecast (AkShare)")

                            return format_tool_result(success_result(result_text))

                elif market == "hk":
                    # 港股业绩预测
                    code_clean = stock_code.replace('.HK', '').replace('.hk', '').zfill(5)
                    df = ak.stock_hk_profit_forecast_et(symbol=code_clean)

                    if df is not None and not df.empty:
                        logger.info(f"✅ AkShare成功获取港股业绩预告: {stock_code}, {len(df)}条记录")

                        # 格式化输出
                        result_text = f"# {stock_code} 港股业绩预告（来源：AkShare-东方财富）\n\n"
                        result_text += _format_result(df, f"{stock_code} Forecast (AkShare)")

                        return format_tool_result(success_result(result_text))

            except Exception as ak_e:
                logger.warning(f"⚠️ AkShare获取{market_name}业绩预告失败: {ak_e}")

        # 5. 两个数据源都失败
        error_msg = f"无法从Tushare和AkShare获取{market_name}业绩数据: {stock_code}, data_type: {data_type}"
        suggestion_msg = "检查数据源配置或尝试其他数据类型" if market in ["cn", "hk"] else "检查Tushare配置或尝试其他数据类型"

        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            error_msg,
            suggestion=suggestion_msg
        ))

    except Exception as e:
        logger.error(f"get_company_performance_unified failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            str(e)
        ))

def get_macro_econ(
    indicator: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> str:
    """
    获取宏观经济数据。

    Args:
        indicator: 指标名称，支持 shibor、lpr、gdp、cpi、ppi、cn_m、cn_pmi、cn_sf 等
        start_date: 开始日期，格式 YYYYMMDD，默认 3 个月前
        end_date: 结束日期，格式 YYYYMMDD，默认今天

    Returns:
        JSON 格式的 ToolResult，包含 status、data、error_code、suggestion 字段
    """
    try:
        # 设置默认日期
        if not end_date:
            end_date = get_current_date_compact()
        if not start_date:
            start_date = (now_utc() - timedelta(days=90)).strftime('%Y%m%d')

        data = get_manager().get_macro_econ(indicator=indicator, start_date=start_date, end_date=end_date)
        return format_tool_result(success_result(_format_result(data, f"Macro: {indicator}")))
    except Exception as e:
        logger.error(f"get_macro_econ failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            str(e)
        ))

def get_money_flow(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    query_type: Optional[str] = None,
    ts_code: Optional[str] = None,
    content_type: Optional[str] = None,
    trade_date: Optional[str] = None
) -> str:
    """
    获取资金流向数据。

    Args:
        start_date: 开始日期，格式 YYYYMMDD，默认 1 个月前
        end_date: 结束日期，格式 YYYYMMDD，默认今天
        query_type: 查询类型，支持 stock(个股)、market(大盘)、sector(板块)
        ts_code: 股票或板块代码
        content_type: 板块类型，支持 industry(行业)、concept(概念)、area(地域)
        trade_date: 指定交易日期，格式 YYYYMMDD

    Returns:
        JSON 格式的 ToolResult，包含 status、data、error_code、suggestion 字段
    """
    try:
        # 设置默认日期 (如果未提供 trade_date)
        if not trade_date:
            if not end_date:
                end_date = get_current_date_compact()
            if not start_date:
                start_date = (now_utc() - timedelta(days=30)).strftime('%Y%m%d')

        data = get_manager().get_money_flow(
            start_date=start_date,
            end_date=end_date,
            query_type=query_type,
            ts_code=ts_code,
            content_type=content_type,
            trade_date=trade_date
        )
        return format_tool_result(success_result(_format_result(data, f"Money Flow: {ts_code or query_type}")))
    except Exception as e:
        logger.error(f"get_money_flow failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            str(e)
        ))

def get_margin_trade(
    data_type: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    ts_code: Optional[str] = None,
    exchange: Optional[str] = None
) -> str:
    """
    获取融资融券数据。

    Args:
        data_type: 数据类型，支持 margin_secs、margin、margin_detail、slb_len_mm
        start_date: 开始日期，格式 YYYYMMDD，默认 1 个月前
        end_date: 结束日期，格式 YYYYMMDD，默认今天
        ts_code: 股票代码
        exchange: 交易所，支持 SSE、SZSE、BSE

    Returns:
        JSON 格式的 ToolResult，包含 status、data、error_code、suggestion 字段
    """
    try:
        # 设置默认日期
        if not end_date:
            end_date = get_current_date_compact()
        if not start_date:
            start_date = (now_utc() - timedelta(days=30)).strftime('%Y%m%d')

        # 🔥 优先使用Tushare获取融资融券数据
        try:
            logger.info(f"📊 尝试使用Tushare获取融资融券数据: {data_type}")
            data = get_manager().get_margin_trade(
                data_type=data_type,
                start_date=start_date,
                end_date=end_date,
                ts_code=ts_code,
                exchange=exchange
            )
            if data and not data.empty:
                logger.info(f"✅ Tushare成功获取融资融券数据: {data_type}, {len(data)}条记录")
                return format_tool_result(success_result(_format_result(data, f"Margin Trade: {data_type}")))
        except Exception as tu_e:
            logger.info(f"⚠️ Tushare获取融资融券数据失败: {tu_e}，尝试AkShare")

        # 回退到AkShare（暂不支持融资融券明细数据）
        # AkShare不提供个股融资融券明细接口，仅提供融资融券汇总数据
        logger.info(f"⚠️ AkShare暂不支持个股融资融券明细数据，仅Tushare支持")

        # 两个数据源都失败
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            f"无法从Tushare和AkShare获取融资融券数据: {data_type}"
        ))
    except Exception as e:
        logger.error(f"get_margin_trade failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            str(e)
        ))

# --- 4. Funds ---

def get_fund_data(
    ts_code: str,
    data_type: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    period: Optional[str] = None
) -> str:
    """
    获取公募基金数据。

    Args:
        ts_code: 基金代码
        data_type: 数据类型，支持 basic、manager、nav、dividend、portfolio、all
        start_date: 开始日期，格式 YYYYMMDD，默认 3 个月前
        end_date: 结束日期，格式 YYYYMMDD，默认今天
        period: 报告期，可选

    Returns:
        JSON 格式的 ToolResult，包含 status、data、error_code、suggestion 字段
    """
    try:
        # 设置默认日期
        if not end_date:
            end_date = get_current_date_compact()
        if not start_date:
            start_date = (now_utc() - timedelta(days=90)).strftime('%Y%m%d')

        # 🔥 优先使用Tushare获取基金数据
        try:
            logger.info(f"📊 尝试使用Tushare获取基金数据: {ts_code}, 类型: {data_type}")
            data = get_manager().get_fund_data(
                ts_code=ts_code,
                data_type=data_type,
                start_date=start_date,
                end_date=end_date,
                period=period
            )
            if data and not data.empty:
                logger.info(f"✅ Tushare成功获取基金数据: {ts_code}, {len(data)}条记录")
                return format_tool_result(success_result(_format_result(data, f"Fund: {ts_code} {data_type}")))
        except Exception as tu_e:
            logger.info(f"⚠️ Tushare获取基金数据失败: {tu_e}，尝试AkShare")

        # 回退到AkShare（仅支持basic、nav、all类型）
        if data_type in ["basic", "nav", "all"]:
            try:
                import akshare as ak
                import pandas as pd

                logger.info(f"📊 尝试使用AkShare获取基金数据: {ts_code}, 类型: {data_type}")

                # 获取基金信息（注意：fund_open_fund_info_em不需要year参数）
                df = ak.fund_open_fund_info_em(symbol=ts_code)

                if df is not None and not df.empty:
                    logger.info(f"✅ AkShare成功获取基金数据: {ts_code}")

                    # 格式化数据
                    result_text = f"# {ts_code} 基金数据（来源：AkShare）\n\n"
                    result_text += f"**数据类型**: {data_type}\n\n"

                    result_text += "## 基金信息\n\n"
                    for col in df.columns:
                        value = df.iloc[0][col]
                        # 处理NaN值
                        if pd.notna(value):
                            result_text += f"- **{col}**: {value}\n"

                    return result_text
                else:
                    logger.warning(f"⚠️ AkShare未获取到基金数据")
            except Exception as ak_e:
                logger.warning(f"⚠️ AkShare获取基金数据失败: {ak_e}")

        # 两个数据源都失败
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            f"无法从Tushare和AkShare获取基金数据: {ts_code}, data_type: {data_type}"
        ))
    except Exception as e:
        logger.error(f"get_fund_data failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            str(e)
        ))

def get_fund_manager_by_name(
    name: str,
    ann_date: Optional[str] = None
) -> str:
    """
    根据姓名获取基金经理信息。

    Args:
        name: 基金经理姓名
        ann_date: 公告日期，格式 YYYYMMDD，可选

    Returns:
        JSON 格式的 ToolResult，包含 status、data、error_code、suggestion 字段
    """
    try:
        data = get_manager().get_fund_manager_by_name(name=name, ann_date=ann_date)
        return format_tool_result(success_result(_format_result(data, f"Manager: {name}")))
    except Exception as e:
        logger.error(f"get_fund_manager_by_name failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            str(e)
        ))

# --- 5. Index & Others ---

def get_index_data(
    stock_code: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> str:
    """
    获取指数日线行情。

    Args:
        stock_code: 指数代码，如 "000001.SH"
        start_date: 开始日期，格式 YYYYMMDD，默认 3 个月前
        end_date: 结束日期，格式 YYYYMMDD，默认今天

    Returns:
        JSON 格式的 ToolResult，包含 status、data、error_code、suggestion 字段
    """
    try:
        # 设置默认日期
        if not end_date:
            end_date = get_current_date_compact()
        if not start_date:
            start_date = (now_utc() - timedelta(days=90)).strftime('%Y%m%d')

        data = get_manager().get_index_data(code=stock_code, start_date=start_date, end_date=end_date)
        return format_tool_result(success_result(_format_result(data, f"Index: {stock_code}")))
    except Exception as e:
        logger.error(f"get_index_data failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            str(e)
        ))

def get_csi_index_constituents(
    index_code: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> str:
    """
    获取中证指数成份股及权重。

    Args:
        index_code: 指数代码
        start_date: 开始日期，格式 YYYYMMDD，默认 1 个月前
        end_date: 结束日期，格式 YYYYMMDD，默认今天

    Returns:
        JSON 格式的 ToolResult，包含 status、data、error_code、suggestion 字段
    """
    try:
        # 设置默认日期
        if not end_date:
            end_date = get_current_date_compact()
        if not start_date:
            start_date = (now_utc() - timedelta(days=30)).strftime('%Y%m%d')

        data = get_manager().get_csi_index_constituents(index_code=index_code, start_date=start_date, end_date=end_date)
        return format_tool_result(success_result(_format_result(data, f"CSI Constituents: {index_code}")))
    except Exception as e:
        logger.error(f"get_csi_index_constituents failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            str(e)
        ))

def get_convertible_bond(
    data_type: str,
    ts_code: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> str:
    """
    获取可转债数据。

    Args:
        data_type: 数据类型，支持 issue(发行信息)、info(基本信息)
        ts_code: 转债代码
        start_date: 开始日期，格式 YYYYMMDD
        end_date: 结束日期，格式 YYYYMMDD

    Returns:
        JSON 格式的 ToolResult，包含 status、data、error_code、suggestion 字段
    """
    try:
        import os

        # 🔥 优先使用Tushare获取可转债数据（仅当配置了token时）
        tushare_token = os.getenv("TUSHARE_TOKEN")
        if tushare_token and tushare_token.strip():
            try:
                logger.info(f"📊 尝试使用Tushare获取可转债数据: 类型{data_type}")
                data = get_manager().get_convertible_bond(
                    data_type=data_type,
                    ts_code=ts_code,
                    start_date=start_date,
                    end_date=end_date
                )
                if data and not data.empty:
                    logger.info(f"✅ Tushare成功获取可转债数据: {len(data)}条记录")
                    return format_tool_result(success_result(_format_result(data, f"CB: {data_type}")))
            except Exception as tu_e:
                logger.info(f"⚠️ Tushare获取可转债数据失败: {tu_e}，尝试AkShare")
        else:
            logger.debug("⚠️ 未配置Tushare token，直接使用AkShare")

        # 回退到AkShare
        try:
            import akshare as ak
            import pandas as pd

            logger.info(f"📊 尝试使用AkShare获取可转债数据: 类型{data_type}")

            # 获取可转债数据
            df = ak.bond_cb_jsl()

            if df is not None and not df.empty:
                logger.info(f"✅ AkShare成功获取可转债数据: {len(df)}条记录")

                # 如果指定了转债代码，进行过滤（尝试所有可能的列名）
                if ts_code:
                    df_filtered = None
                    # 尝试直接在所有列中查找匹配的值
                    for col in df.columns:
                        if df[col].dtype == 'object':
                            matched = df[df[col].astype(str).str.contains(ts_code, na=False)]
                            if not matched.empty:
                                df_filtered = matched
                                logger.info(f"✅ 在列'{col}'中找到{ts_code}的可转债数据")
                                break

                    if df_filtered is None or df_filtered.empty:
                        logger.info(f"⚠️ AkShare未找到{ts_code}的可转债数据，返回全部数据")
                        df_filtered = df
                    else:
                        logger.info(f"✅ AkShare找到{ts_code}的可转债数据: {len(df_filtered)}条记录")
                else:
                    df_filtered = df

                # 按日期范围过滤（如果提供了日期）
                if start_date or end_date:
                    # 尝试找到日期列并过滤
                    date_col = None
                    for col in df_filtered.columns:
                        # 检查第一行数据是否为datetime类型
                        if len(df_filtered) > 0:
                            sample_val = df_filtered[col].iloc[0]
                            # 使用pd.Timestamp而不是datetime来避免变量冲突
                            if isinstance(sample_val, pd.Timestamp):
                                date_col = col
                                break

                    if date_col:
                        if start_date:
                            # 使用pd.to_datetime解析日期字符串，避免datetime变量冲突
                            start_dt = pd.to_datetime(start_date)
                            df_filtered = df_filtered[df_filtered[date_col] >= start_dt]

                        if end_date:
                            end_dt = pd.to_datetime(end_date)
                            df_filtered = df_filtered[df_filtered[date_col] <= end_dt]

                        logger.info(f"✅ 按日期范围过滤后剩余: {len(df_filtered)}条记录")

                # 返回JSON格式
                data_dict = df_filtered.head(50).to_dict(orient='records')
                json_data = json.dumps(data_dict, ensure_ascii=False, default=str)
                return format_tool_result(success_result(
                    data=json_data,
                ))
            else:
                logger.warning(f"⚠️ AkShare可转债接口返回空数据")
        except Exception as ak_e:
            logger.warning(f"⚠️ AkShare获取可转债数据失败: {ak_e}")

        # 两个数据源都失败
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            f"无法从Tushare和AkShare获取可转债数据: {data_type}"
        ))
    except Exception as e:
        logger.error(f"get_convertible_bond failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            str(e)
        ))

def get_block_trade(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    code: Optional[str] = None
) -> str:
    """
    获取大宗交易数据。

    Args:
        start_date: 开始日期，格式 YYYYMMDD，默认 7 天前
        end_date: 结束日期，格式 YYYYMMDD，默认今天
        code: 股票代码，可选

    Returns:
        JSON 格式的 ToolResult，包含 status、data、error_code、suggestion 字段
    """
    try:
        import os

        # 设置默认日期
        if not end_date:
            end_date = get_current_date_compact()
        if not start_date:
            start_date = (now_utc() - timedelta(days=7)).strftime('%Y%m%d')

        # 🔥 优先使用Tushare获取大宗交易数据（仅当配置了token时）
        tushare_token = os.getenv("TUSHARE_TOKEN")
        if tushare_token and tushare_token.strip():
            try:
                logger.info(f"📊 尝试使用Tushare获取大宗交易数据")
                data = get_manager().get_block_trade(start_date=start_date, end_date=end_date, code=code)
                if data and not data.empty:
                    logger.info(f"✅ Tushare成功获取大宗交易数据: {len(data)}条记录")
                    return format_tool_result(success_result(_format_result(data, f"Block Trade: {code or 'All'}")))
            except Exception as tu_e:
                logger.info(f"⚠️ Tushare获取大宗交易数据失败: {tu_e}，尝试AkShare")
        else:
            logger.debug("⚠️ 未配置Tushare token，直接使用AkShare")

        # 回退到AkShare
        try:
            import akshare as ak
            import pandas as pd

            logger.info(f"📊 尝试使用AkShare获取大宗交易数据: 日期范围{start_date}-{end_date}")

            # 使用正确的AkShare大宗交易接口：stock_dzjy_mrmx（每日明细）
            df = ak.stock_dzjy_mrmx(symbol='A股', start_date=start_date, end_date=end_date)

            if df is not None and not df.empty:
                logger.info(f"✅ AkShare成功获取大宗交易数据: {len(df)}条记录")

                # 如果指定了股票代码，进行过滤
                if code:
                    code_6digit = code.replace('.SH', '').replace('.SZ', '').replace('.sh', '').replace('.sz', '').zfill(6)
                    # 尝试多种可能的列名（根据实际测试）
                    for col_name in ['证券代码', '代码', 'symbol', 'stock_code']:
                        if col_name in df.columns:
                            df_filtered = df[df[col_name] == code_6digit]
                            if not df_filtered.empty:
                                break
                    else:
                        df_filtered = df

                    if df_filtered.empty:
                        logger.info(f"⚠️ AkShare未找到{code}的大宗交易数据，返回全部数据")
                        df_filtered = df
                    else:
                        logger.info(f"✅ AkShare找到{code}的大宗交易数据: {len(df_filtered)}条记录")
                else:
                    df_filtered = df

                # 返回JSON格式
                data_dict = df_filtered.head(50).to_dict(orient='records')
                json_data = json.dumps(data_dict, ensure_ascii=False, default=str)
                return format_tool_result(success_result(
                    data=json_data,
                ))
            else:
                logger.warning(f"⚠️ AkShare大宗交易接口返回空数据")
        except Exception as ak_e:
            logger.warning(f"⚠️ AkShare获取大宗交易数据失败: {ak_e}")

        # 两个数据源都失败
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            f"无法从Tushare和AkShare获取大宗交易数据"
        ))
    except Exception as e:
        logger.error(f"get_block_trade failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            str(e)
        ))

def get_dragon_tiger_inst(
    trade_date: Optional[str] = None,
    ts_code: Optional[str] = None
) -> str:
    """
    获取龙虎榜机构明细。

    Args:
        trade_date: 交易日期，格式 YYYYMMDD，默认今天
        ts_code: 股票代码，可选

    Returns:
        JSON 格式的 ToolResult，包含 status、data、error_code、suggestion 字段
    """
    try:
        import os

        # 设置默认日期
        if not trade_date:
            trade_date = get_current_date_compact()

        # 🔥 优先使用Tushare获取龙虎榜数据（仅当配置了token时）
        tushare_token = os.getenv("TUSHARE_TOKEN")
        if tushare_token and tushare_token.strip():
            try:
                logger.info(f"📊 尝试使用Tushare获取龙虎榜数据: 日期{trade_date}")
                data = get_manager().get_dragon_tiger_inst(trade_date=trade_date, ts_code=ts_code)
                if data and not data.empty:
                    logger.info(f"✅ Tushare成功获取龙虎榜数据: {len(data)}条记录")
                    return format_tool_result(success_result(_format_result(data, f"Dragon Tiger: {trade_date}")))
            except Exception as tu_e:
                logger.info(f"⚠️ Tushare获取龙虎榜数据失败: {tu_e}，尝试AkShare")
        else:
            logger.debug("⚠️ 未配置Tushare token，直接使用AkShare")

        # 回退到AkShare
        try:
            import akshare as ak
            import pandas as pd

            logger.info(f"📊 尝试使用AkShare获取龙虎榜数据: 日期{trade_date}")

            # 获取龙虎榜数据
            df = None
            try:
                # 方法1：使用东方财富龙虎榜接口（需要start_date和end_date）
                df = ak.stock_lhb_detail_em(start_date=trade_date, end_date=trade_date)
                # 检查是否返回None（API在某些日期可能没有数据）
                if df is None:
                    logger.warning(f"⚠️ stock_lhb_detail_em返回None（{trade_date}可能没有龙虎榜数据）")
                else:
                    logger.info(f"✅ 使用stock_lhb_detail_em成功获取数据: {len(df)}条记录")
            except Exception as em_e:
                logger.warning(f"⚠️ stock_lhb_detail_em失败: {em_e}，尝试其他接口")
                try:
                    # 方法2：尝试使用新浪龙虎榜接口
                    df = ak.stock_lhb_detail_daily_sina(date=trade_date)
                    logger.info(f"✅ 使用stock_lhb_detail_daily_sina成功获取数据")
                except Exception as sina_e:
                    logger.warning(f"⚠️ stock_lhb_detail_daily_sina也失败: {sina_e}")
                    df = None

            if df is not None and not df.empty:
                # 如果指定了股票代码，进行过滤
                if ts_code:
                    code_6digit = ts_code.replace('.SH', '').replace('.SZ', '').replace('.sh', '').replace('.sz', '').zfill(6)
                    # 尝试多种可能的列名
                    df_filtered = None
                    for col_name in ['代码', '股票代码', 'symbol', 'stock_code']:
                        if col_name in df.columns:
                            df_filtered = df[df[col_name] == code_6digit]
                            if not df_filtered.empty:
                                break

                    if df_filtered is None or df_filtered.empty:
                        logger.info(f"⚠️ AkShare未找到{ts_code}的龙虎榜数据，返回全部数据")
                        df_filtered = df
                    else:
                        logger.info(f"✅ AkShare找到{ts_code}的龙虎榜数据: {len(df_filtered)}条记录")
                else:
                    df_filtered = df

                logger.info(f"✅ AkShare成功获取龙虎榜数据: {len(df_filtered)}条记录")

                # 返回JSON格式
                data_dict = df_filtered.head(50).to_dict(orient='records')
                json_data = json.dumps(data_dict, ensure_ascii=False, default=str)
                return format_tool_result(success_result(
                    data=json_data,
                ))
            else:
                logger.warning(f"⚠️ AkShare龙虎榜接口返回空数据")
        except Exception as ak_e:
            logger.warning(f"⚠️ AkShare获取龙虎榜数据失败: {ak_e}")

        # 两个数据源都失败
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            f"无法从Tushare和AkShare获取龙虎榜数据: {trade_date}"
        ))
    except Exception as e:
        logger.error(f"get_dragon_tiger_inst failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            str(e)
        ))

# --- 6. News ---

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
        return format_tool_result(success_result(_format_result(data, f"News: {query}")))
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
        return format_tool_result(success_result(_format_result(data, "Hot News 7x24")))
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

# --- Helpers ---

def _format_result(data: Any, title: str, max_rows: int = 2000) -> str:
    """Format data to Markdown"""
    if data is None:
        return f"# {title}\n\nNo data found."

    if isinstance(data, list) and not data:
        return f"# {title}\n\nNo data found."

    if isinstance(data, str):
        # 如果字符串本身已经是Markdown表格，尝试截断行数
        if "|" in data and data.count('\n') > max_rows + 5:
            lines = data.split('\n')
            # 保留头部和前 max_rows 行
            # 假设前两行是表头
            header = lines[:2]
            content = lines[2:]
            if len(content) > max_rows:
                truncated_content = content[:max_rows]
                return "\n".join(header + truncated_content + [f"\n... (剩余 {len(content) - max_rows} 行已隐藏)"])
        return data

    # Assuming data is a list of dicts or a pandas DataFrame (converted to list of dicts)
    if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
        # Truncate list if too long
        original_len = len(data)
        if original_len > max_rows:
            data = data[:max_rows]

        # Create markdown table
        headers = list(data[0].keys())
        header_row = "| " + " | ".join(headers) + " |"
        separator_row = "| " + " | ".join(["---"] * len(headers)) + " |"

        rows = []
        for item in data:
            row = "| " + " | ".join([str(item.get(h, "")) for h in headers]) + " |"
            rows.append(row)

        result = f"# {title}\n\n{header_row}\n{separator_row}\n" + "\n".join(rows)

        if original_len > max_rows:
            result += f"\n\n... (剩余 {original_len - max_rows} 行已隐藏)"

        return result

    return f"# {title}\n\n{str(data)}"
