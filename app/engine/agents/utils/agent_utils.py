from langchain_core.messages import HumanMessage, AIMessage
from typing import List
from typing import Annotated
from langchain_core.messages import RemoveMessage
from langchain_core.tools import tool
from datetime import date, timedelta, datetime
import functools
import pandas as pd
import os
from langchain_openai import ChatOpenAI
import asyncio
from app.data.core.interface import DataInterface
from app.engine.default_config import DEFAULT_CONFIG

# 导入统一日志系统和工具日志装饰器
from app.utils.logging_init import get_logger
from app.utils.tool_logging import log_tool_call, log_analysis_step
from app.utils.time_utils import now_utc, get_current_date

logger = get_logger('agents')


def _run_async(coro):
    """安全地在同步上下文中执行异步协程。

    当已有运行中的事件循环时（如 FastAPI 中），使用线程池执行；
    否则直接使用 asyncio.run()。
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result(timeout=60)
    else:
        return asyncio.run(coro)


def _get_stock_data_sync(market, symbol, start_date=None, end_date=None):
    """同步获取股票日线数据，返回格式化的字符串。"""
    try:
        di = DataInterface.get_instance()
        result = _run_async(di.read(market, "daily_quotes", symbol=symbol, start_date=start_date, end_date=end_date))
        data = result.get("data")
        if data:
            return pd.DataFrame(data).to_string()
    except Exception:
        pass
    return None


def _get_stock_info_sync(market, symbol):
    """同步获取股票基础信息，返回格式化的字符串。"""
    try:
        di = DataInterface.get_instance()
        result = _run_async(di.read(market, "basic_info", symbol=symbol))
        data = result.get("data")
        if data:
            doc = data[0] if isinstance(data, list) and data else data
            lines = [f"股票代码: {doc.get('symbol', symbol)}"]
            if doc.get("name"):
                lines.append(f"股票名称: {doc.get('name')}")
            if doc.get("industry"):
                lines.append(f"行业: {doc.get('industry')}")
            if doc.get("exchange"):
                lines.append(f"交易所: {doc.get('exchange')}")
            return "\n".join(lines)
    except Exception:
        pass
    return None


def _get_us_news_sync(symbol):
    """同步获取美股新闻数据，返回格式化的字符串。"""
    try:
        di = DataInterface.get_instance()
        result = _run_async(di.read("US", "news", symbol=symbol.upper()))
        data = result.get("data")
        if data:
            return str(data)
    except Exception:
        pass
    return None


def _get_us_daily_quotes_sync(symbol, start_date=None, end_date=None):
    """同步获取美股日线数据，返回 DataFrame 字符串。"""
    try:
        di = DataInterface.get_instance()
        result = _run_async(di.read("US", "daily_quotes", symbol=symbol.upper(), start_date=start_date, end_date=end_date))
        data = result.get("data")
        if data:
            return pd.DataFrame(data).to_string()
    except Exception:
        pass
    return None


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

    @staticmethod
    @tool
    def get_finnhub_news(
        ticker: Annotated[
            str,
            "Search query of a company, e.g. 'AAPL, TSM, etc.",
        ],
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

    @staticmethod
    @tool
    def get_reddit_stock_info(
        ticker: Annotated[
            str,
            "Ticker of a company. e.g. AAPL, TSM",
        ],
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

    @staticmethod
    @tool
    def get_china_market_overview(
        curr_date: Annotated[str, "当前日期，格式 yyyy-mm-dd"],
    ) -> str:
        """
        获取中国股市整体概览，包括主要指数的实时行情。
        涵盖上证指数、深证成指、创业板指、科创50等主要指数。
        Args:
            curr_date (str): 当前日期，格式 yyyy-mm-dd
        Returns:
            str: 包含主要指数实时行情的市场概览报告
        """
        try:
            # 使用DataInterface获取主要指数数据
            from app.data.core.interface import DataInterface

            di = DataInterface.get_instance()

            indices_map = {}
            for idx_code, idx_name in [("000001", "上证指数"), ("399001", "深证成指"), ("399006", "创业板指")]:
                try:
                    r = _run_async(di.read("CN", "market_quotes", symbol=idx_code))
                    d = r.get("data")
                    if d:
                        doc = d[0] if isinstance(d, list) and d else d
                        indices_map[idx_name] = f"{doc.get('close', 'N/A')} ({doc.get('pct_chg', 'N/A')}%)"
                except Exception:
                    indices_map[idx_name] = "数据获取中..."

            indices_lines = "\n".join([f"- {k}: {v}" for k, v in indices_map.items()])

            return f"""# 中国股市概览 - {curr_date}

## 📊 主要指数
{indices_lines}

## 💡 说明
市场概览数据通过统一数据平台获取。

数据来源: 统一数据平台 (DataInterface)
更新时间: {curr_date}
"""

        except Exception as e:
            return f"中国市场概览获取失败: {str(e)}"

    @staticmethod
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
            import asyncio
            di = DataInterface.get_instance()
            market = "CN"
            if ticker and (".HK" in ticker or ticker.isdigit() and len(ticker) == 5 and ticker[0] == "0"):
                market = "HK"
            elif ticker and ticker.isalpha() and ticker == ticker.upper():
                market = "US"
            result = _run_async(
                di.read(market, "news", symbol=ticker)
            )
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

    @staticmethod
    @tool
    @log_tool_call(tool_name="get_stock_fundamentals_unified", log_args=True)
    def get_stock_fundamentals_unified(
        ticker: Annotated[str, "股票代码（支持A股、港股、美股）"],
        start_date: Annotated[str, "开始日期，格式：YYYY-MM-DD"] = None,
        end_date: Annotated[str, "结束日期，格式：YYYY-MM-DD"] = None,
        curr_date: Annotated[str, "当前日期，格式：YYYY-MM-DD"] = None
    ) -> str:
        """
        统一的股票基本面分析工具
        自动识别股票类型（A股、港股、美股）并调用相应的数据源
        支持基于分析级别的数据获取策略

        Args:
            ticker: 股票代码（如：000001、0700.HK、AAPL）
            start_date: 开始日期（可选，格式：YYYY-MM-DD）
            end_date: 结束日期（可选，格式：YYYY-MM-DD）
            curr_date: 当前日期（可选，格式：YYYY-MM-DD）

        Returns:
            str: 基本面分析数据和报告
        """
        logger.info(f"📊 [统一基本面工具] 分析股票: {ticker}")

        # 分级分析已废弃，统一使用标准深度
        data_depth = "standard"
        logger.info("🔧 [分析深度] 已取消分级，使用标准数据深度获取策略")

        # 添加详细的股票代码追踪日志
        logger.debug(f"🔍 [股票代码追踪] 统一基本面工具接收到的原始股票代码: '{ticker}' (类型: {type(ticker)})")
        logger.debug(f"🔍 [股票代码追踪] 股票代码长度: {len(str(ticker))}")
        logger.debug(f"🔍 [股票代码追踪] 股票代码字符: {list(str(ticker))}")

        # 保存原始ticker用于对比
        original_ticker = ticker

        try:
            from app.utils.stock_utils import StockUtils
            from datetime import datetime, timedelta

            # 自动识别股票类型
            market_info = StockUtils.get_market_info(ticker)
            is_china = market_info['is_china']
            is_hk = market_info['is_hk']
            is_us = market_info['is_us']

            logger.debug(f"🔍 [股票代码追踪] StockUtils.get_market_info 返回的市场信息: {market_info}")
            logger.info(f"📊 [统一基本面工具] 股票类型: {market_info['market_name']}")
            logger.info(f"📊 [统一基本面工具] 货币: {market_info['currency_name']} ({market_info['currency_symbol']})")

            # 检查ticker是否在处理过程中发生了变化
            if str(ticker) != str(original_ticker):
                logger.warning(f"🔍 [股票代码追踪] 警告：股票代码发生了变化！原始: '{original_ticker}' -> 当前: '{ticker}'")

            # 设置默认日期
            if not curr_date:
                curr_date = get_current_date()

            # 基本面分析优化：不需要大量历史数据，只需要当前价格和财务数据
            # 根据数据深度级别设置不同的分析模块数量，而非历史数据范围
            # 🔧 修正映射关系：analysis_modules 应该与 data_depth 保持一致
            if data_depth == "basic":  # 快速分析：基础模块
                analysis_modules = "basic"
                logger.debug(f"📊 [基本面策略] 快速分析模式：获取基础财务指标")
            elif data_depth == "standard":  # 基础/标准分析：标准模块
                analysis_modules = "standard"
                logger.debug(f"📊 [基本面策略] 标准分析模式：获取标准财务分析")
            elif data_depth == "full":  # 深度分析：完整模块
                analysis_modules = "full"
                logger.debug(f"📊 [基本面策略] 深度分析模式：获取完整基本面分析")
            elif data_depth == "comprehensive":  # 全面分析：综合模块
                analysis_modules = "comprehensive"
                logger.debug(f"📊 [基本面策略] 全面分析模式：获取综合基本面分析")
            else:
                analysis_modules = "standard"  # 默认标准分析
                logger.debug(f"📊 [基本面策略] 默认模式：获取标准基本面分析")

            # 基本面分析策略：
            # 1. 获取10天数据（保证能拿到数据，处理周末/节假日）
            # 2. 只使用最近2天数据参与分析（仅需当前价格）
            days_to_fetch = 10  # 固定获取10天数据
            days_to_analyze = 2  # 只分析最近2天

            logger.debug(f"📅 [基本面策略] 获取{days_to_fetch}天数据，分析最近{days_to_analyze}天")

            if not start_date:
                start_date = (now_utc() - timedelta(days=days_to_fetch)).strftime('%Y-%m-%d')

            if not end_date:
                end_date = curr_date

            result_data = []

            if is_china:
                # 中国A股：基本面分析优化策略 - 只获取必要的当前价格和基本面数据
                logger.debug(f"🇨🇳 [统一基本面工具] 处理A股数据，数据深度: {data_depth}...")
                logger.debug(f"🔍 [股票代码追踪] 进入A股处理分支，ticker: '{ticker}'")
                logger.debug(f"💡 [优化策略] 基本面分析只获取当前价格和财务数据，不获取历史日线数据")

                # 优化策略：基本面分析不需要大量历史日线数据
                # 只获取当前股价信息（最近1-2天即可）和基本面财务数据
                try:
                    # 获取最新股价信息（只需要最近1-2天的数据）
                    from datetime import datetime, timedelta
                    recent_end_date = curr_date
                    recent_start_date = (datetime.strptime(curr_date, '%Y-%m-%d') - timedelta(days=2)).strftime('%Y-%m-%d')

                    logger.debug(f"🔍 [股票代码追踪] 调用 _get_stock_data_sync（仅获取最新价格），传入参数: market='CN', ticker='{ticker}', start_date='{recent_start_date}', end_date='{recent_end_date}'")
                    current_price_data = _get_stock_data_sync("CN", ticker, recent_start_date, recent_end_date)

                    # 🔍 调试：打印返回数据的前500字符
                    logger.debug(f"🔍 [基本面工具调试] A股价格数据返回长度: {len(current_price_data)}")
                    logger.debug(f"🔍 [基本面工具调试] A股价格数据前500字符:\n{current_price_data[:500]}")

                    result_data.append(f"## A股当前价格信息\n{current_price_data}")
                except Exception as e:
                    logger.error(f"❌ [基本面工具调试] A股价格数据获取失败: {e}")
                    result_data.append(f"## A股当前价格信息\n获取失败: {e}")
                    current_price_data = ""

                try:
                    from app.services.fundamentals import get_fundamentals_provider
                    import asyncio
                    _fp = get_fundamentals_provider()
                    fundamentals_raw = _run_async(_fp.get_fundamentals(ticker))
                    if fundamentals_raw:
                        fundamentals_data = str(fundamentals_raw)
                    else:
                        fundamentals_data = "暂无基本面数据"

                    result_data.append(f"## A股基本面财务数据\n{fundamentals_data}")
                except Exception as e:
                    logger.error(f"❌ [基本面工具调试] A股基本面数据获取失败: {e}")
                    result_data.append(f"## A股基本面财务数据\n获取失败: {e}")

            elif is_hk:
                # 港股：使用AKShare数据源，支持多重备用方案
                logger.debug(f"🇭🇰 [统一基本面工具] 处理港股数据，数据深度: {data_depth}...")

                hk_data_success = False

                # 🔥 统一策略：所有级别都获取完整数据
                # 原因：提示词是统一的，如果数据不完整会导致LLM基于不存在的数据进行分析（幻觉）
                logger.debug(f"🔍 [港股基本面] 统一策略：获取完整数据（忽略 data_depth 参数）")

                # 主要数据源：AKShare
                try:
                    hk_data = _get_stock_data_sync("HK", ticker, start_date, end_date)

                    # 🔍 调试：打印返回数据的前500字符
                    logger.debug(f"🔍 [基本面工具调试] 港股数据返回长度: {len(hk_data)}")
                    logger.debug(f"🔍 [基本面工具调试] 港股数据前500字符:\n{hk_data[:500]}")

                    # 检查数据质量
                    if hk_data and len(hk_data) > 100 and "❌" not in hk_data:
                        result_data.append(f"## 港股数据\n{hk_data}")
                        hk_data_success = True
                        logger.debug(f"✅ [统一基本面工具] 港股主要数据源成功")
                    else:
                        logger.warning(f"⚠️ [统一基本面工具] 港股主要数据源质量不佳")

                except Exception as e:
                    logger.error(f"❌ [基本面工具调试] 港股数据获取失败: {e}")

                # 备用方案：基础港股信息
                if not hk_data_success:
                    try:
                        hk_info_str = _get_stock_info_sync("HK", ticker)

                        basic_info = f"""## 港股基础信息

{hk_info_str or f'股票代码: {ticker}'}
**交易货币**: 港币 (HK$)
**交易所**: 香港交易所 (HKG)

⚠️ 注意：详细的价格和财务数据暂时无法获取，建议稍后重试或使用其他数据源。

**基本面分析建议**：
- 建议查看公司最新财报
- 关注港股市场整体走势
- 考虑汇率因素对投资的影响
"""
                        result_data.append(basic_info)
                        logger.debug(f"✅ [统一基本面工具] 港股备用信息成功")

                    except Exception as e2:
                        # 最终备用方案
                        fallback_info = f"""## 港股信息（备用）

**股票代码**: {ticker}
**股票类型**: 港股
**交易货币**: 港币 (HK$)
**交易所**: 香港交易所 (HKG)

❌ 数据获取遇到问题: {str(e2)}

**建议**：
- 请稍后重试
- 或使用其他数据源
- 检查股票代码格式是否正确
"""
                        result_data.append(fallback_info)
                        logger.error(f"❌ [统一基本面工具] 港股所有数据源都失败: {e2}")

            else:
                # 美股：使用OpenAI/Finnhub数据源
                logger.debug(f"🇺🇸 [统一基本面工具] 处理美股数据...")

                # 🔥 统一策略：所有级别都获取完整数据
                # 原因：提示词是统一的，如果数据不完整会导致LLM基于不存在的数据进行分析（幻觉）
                logger.debug(f"🔍 [美股基本面] 统一策略：获取完整数据（忽略 data_depth 参数）")

                try:
                    from app.data.core.interface import DataInterface
                    import asyncio as _asyncio
                    _di = DataInterface.get_instance()
                    _r = _run_async(_di.read("US", "financial_data", symbol=ticker.upper()))
                    us_data = _r.get("data")
                    result_data.append(f"## 美股基本面数据\n{us_data}")
                    logger.debug(f"✅ [统一基本面工具] 美股数据获取成功")
                except Exception as e:
                    result_data.append(f"## 美股基本面数据\n获取失败: {e}")
                    logger.error(f"❌ [统一基本面工具] 美股数据获取失败: {e}")

            # 组合所有数据
            combined_result = f"""# {ticker} 基本面分析数据

**股票类型**: {market_info['market_name']}
**货币**: {market_info['currency_name']} ({market_info['currency_symbol']})
**分析日期**: {curr_date}
**数据深度级别**: {data_depth}

{chr(10).join(result_data)}

---
*数据来源: 根据股票类型自动选择最适合的数据源*
"""

            # 添加详细的数据获取日志
            logger.debug(f"📊 [统一基本面工具] ===== 数据获取完成摘要 =====")
            logger.debug(f"📊 [统一基本面工具] 股票代码: {ticker}")
            logger.info(f"📊 [统一基本面工具] 股票类型: {market_info['market_name']}")
            logger.debug(f"📊 [统一基本面工具] 数据深度级别: {data_depth}")
            logger.debug(f"📊 [统一基本面工具] 获取的数据模块数量: {len(result_data)}")
            logger.info(f"📊 [统一基本面工具] 总数据长度: {len(combined_result)} 字符")
            
            # 记录每个数据模块的详细信息
            for i, data_section in enumerate(result_data, 1):
                section_lines = data_section.split('\n')
                section_title = section_lines[0] if section_lines else "未知模块"
                section_length = len(data_section)
                logger.debug(f"📊 [统一基本面工具] 数据模块 {i}: {section_title} ({section_length} 字符)")
                
                # 如果数据包含错误信息，特别标记
                if "获取失败" in data_section or "❌" in data_section:
                    logger.warning(f"⚠️ [统一基本面工具] 数据模块 {i} 包含错误信息")
                else:
                    logger.debug(f"✅ [统一基本面工具] 数据模块 {i} 获取成功")
            
            # 根据数据深度级别记录具体的获取策略
            if data_depth in ["basic", "standard"]:
                logger.info(f"📊 [统一基本面工具] 基础/标准级别策略: 仅获取核心价格数据和基础信息")
            elif data_depth in ["full", "detailed", "comprehensive"]:
                logger.debug(f"📊 [统一基本面工具] 完整/详细/全面级别策略: 获取价格数据 + 基本面数据")
            else:
                logger.info(f"📊 [统一基本面工具] 默认策略: 获取完整数据")
            
            logger.debug(f"📊 [统一基本面工具] ===== 数据获取摘要结束 =====")
            
            return combined_result

        except Exception as e:
            error_msg = f"统一基本面分析工具执行失败: {str(e)}"
            logger.error(f"❌ [统一基本面工具] {error_msg}")
            return error_msg

    @staticmethod
    @tool
    @log_tool_call(tool_name="get_stock_market_data_unified", log_args=True)
    def get_stock_market_data_unified(
        ticker: Annotated[str, "股票代码（支持A股、港股、美股）"],
        start_date: Annotated[str, "开始日期，格式：YYYY-MM-DD。注意：系统会自动扩展到配置的回溯天数（通常为365天），你只需要传递分析日期即可"],
        end_date: Annotated[str, "结束日期，格式：YYYY-MM-DD。通常与start_date相同，传递当前分析日期即可"]
    ) -> str:
        """
        统一的股票市场数据工具
        自动识别股票类型（A股、港股、美股）并调用相应的数据源获取价格和技术指标数据

        ⚠️ 重要：系统会自动扩展日期范围到配置的回溯天数（通常为365天），以确保技术指标计算有足够的历史数据。
        你只需要传递当前分析日期作为 start_date 和 end_date 即可，无需手动计算历史日期范围。

        Args:
            ticker: 股票代码（如：000001、0700.HK、AAPL）
            start_date: 开始日期（格式：YYYY-MM-DD）。传递当前分析日期即可，系统会自动扩展
            end_date: 结束日期（格式：YYYY-MM-DD）。传递当前分析日期即可

        Returns:
            str: 市场数据和技术分析报告

        示例：
            如果分析日期是 2025-11-09，传递：
            - ticker: "00700.HK"
            - start_date: "2025-11-09"
            - end_date: "2025-11-09"
            系统会自动获取 2024-11-09 到 2025-11-09 的365天历史数据
        """
        logger.debug(f"📈 [统一市场工具] 分析股票: {ticker}")

        try:
            from app.utils.stock_utils import StockUtils

            # 自动识别股票类型
            market_info = StockUtils.get_market_info(ticker)
            is_china = market_info['is_china']
            is_hk = market_info['is_hk']
            is_us = market_info['is_us']

            logger.debug(f"📈 [统一市场工具] 股票类型: {market_info['market_name']}")
            logger.debug(f"📈 [统一市场工具] 货币: {market_info['currency_name']} ({market_info['currency_symbol']}")

            result_data = []

            if is_china:
                # 中国A股：使用中国股票数据源
                logger.info(f"🇨🇳 [统一市场工具] 处理A股市场数据...")

                try:
                    stock_data = _get_stock_data_sync("CN", ticker, start_date, end_date)

                    # 🔍 调试：打印返回数据的前500字符
                    logger.debug(f"🔍 [市场工具调试] A股数据返回长度: {len(stock_data)}")
                    logger.debug(f"🔍 [市场工具调试] A股数据前500字符:\n{stock_data[:500]}")

                    result_data.append(f"## A股市场数据\n{stock_data}")
                except Exception as e:
                    logger.error(f"❌ [市场工具调试] A股数据获取失败: {e}")
                    result_data.append(f"## A股市场数据\n获取失败: {e}")

            elif is_hk:
                # 港股：使用AKShare数据源
                logger.info(f"🇭🇰 [统一市场工具] 处理港股市场数据...")

                try:
                    hk_data = _get_stock_data_sync("HK", ticker, start_date, end_date)

                    # 🔍 调试：打印返回数据的前500字符
                    logger.debug(f"🔍 [市场工具调试] 港股数据返回长度: {len(hk_data)}")
                    logger.debug(f"🔍 [市场工具调试] 港股数据前500字符:\n{hk_data[:500]}")

                    result_data.append(f"## 港股市场数据\n{hk_data}")
                except Exception as e:
                    logger.error(f"❌ [市场工具调试] 港股数据获取失败: {e}")
                    result_data.append(f"## 港股市场数据\n获取失败: {e}")

            else:
                # 美股：优先使用FINNHUB API数据源
                logger.debug(f"🇺🇸 [统一市场工具] 处理美股市场数据...")

                try:
                    from app.data.core.interface import DataInterface
                    import asyncio as _asyncio
                    _di = DataInterface.get_instance()
                    _r = _run_async(_di.read("US", "daily_quotes", symbol=ticker.upper(), start_date=start_date, end_date=end_date))
                    us_data = _r.get("data")
                    result_data.append(f"## 美股市场数据\n{us_data}")
                except Exception as e:
                    result_data.append(f"## 美股市场数据\n获取失败: {e}")

            # 组合所有数据
            combined_result = f"""# {ticker} 市场数据分析

**股票类型**: {market_info['market_name']}
**货币**: {market_info['currency_name']} ({market_info['currency_symbol']})
**分析期间**: {start_date} 至 {end_date}

{chr(10).join(result_data)}

---
*数据来源: 根据股票类型自动选择最适合的数据源*
"""

            logger.debug(f"📈 [统一市场工具] 数据获取完成，总长度: {len(combined_result)}")
            return combined_result

        except Exception as e:
            error_msg = f"统一市场数据工具执行失败: {str(e)}"
            logger.error(f"❌ [统一市场工具] {error_msg}")
            return error_msg

    @staticmethod
    @tool
    @log_tool_call(tool_name="get_stock_news_unified", log_args=True)
    def get_stock_news_unified(
        ticker: Annotated[str, "股票代码（支持A股、港股、美股）"],
        curr_date: Annotated[str, "当前日期，格式：YYYY-MM-DD"]
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
            from datetime import datetime, timedelta

            # 自动识别股票类型
            market_info = StockUtils.get_market_info(ticker)
            is_china = market_info['is_china']
            is_hk = market_info['is_hk']
            is_us = market_info['is_us']

            logger.debug(f"📰 [统一新闻工具] 股票类型: {market_info['market_name']}")

            # 计算新闻查询的日期范围
            end_date = datetime.strptime(curr_date, '%Y-%m-%d')
            start_date = end_date - timedelta(days=7)
            start_date_str = start_date.strftime('%Y-%m-%d')

            result_data = []

            if is_china or is_hk:
                # 中国A股和港股：使用AKShare东方财富新闻和Google新闻（中文搜索）
                logger.debug(f"🇨🇳🇭🇰 [统一新闻工具] 处理中文新闻...")

                # 1. 尝试获取AKShare东方财富新闻
                try:
                    # 处理股票代码
                    clean_ticker = ticker.replace('.SH', '').replace('.SZ', '').replace('.SS', '')\
                                   .replace('.HK', '').replace('.XSHE', '').replace('.XSHG', '')
                    
                    logger.debug(f"🇨🇳🇭🇰 [统一新闻工具] 尝试获取东方财富新闻: {clean_ticker}")

                    # 通过 DataInterface 获取已入库新闻数据
                    try:
                        from app.data.core.interface import DataInterface
                        import asyncio as _asyncio
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
                                news_title = item.get("title", "") or item.get("新闻标题", "")
                                news_time = item.get("publish_time", "") or item.get("发布时间", "")
                                news_url = item.get("url", "") or item.get("新闻链接", "")
                                news_item = f"- **{news_title}** [{news_time}]({news_url})"
                                em_news_items.append(news_item)
                            if em_news_items:
                                em_news_text = "\n".join(em_news_items)
                                result_data.append(f"## 东方财富新闻\n{em_news_text}")
                                logger.debug(f"🇨🇳🇭🇰 [统一新闻工具] 成功获取{len(em_news_items)}条东方财富新闻")
                        else:
                            result_data.append(f"## 东方财富新闻\n暂无新闻数据")
                    except Exception as inner_e:
                        logger.error(f"❌ [统一新闻工具] 东方财富新闻获取失败: {inner_e}")
                        result_data.append(f"## 东方财富新闻\n获取失败: {inner_e}")
                except Exception as em_e:
                    logger.error(f"❌ [统一新闻工具] 东方财富新闻获取失败: {em_e}")
                    result_data.append(f"## 东方财富新闻\n获取失败: {em_e}")

                # 2. 获取Google新闻作为补充
                try:
                    # 获取公司中文名称用于搜索
                    if is_china:
                        # A股使用股票代码搜索，添加更多中文关键词
                        clean_ticker = ticker.replace('.SH', '').replace('.SZ', '').replace('.SS', '')\
                                       .replace('.XSHE', '').replace('.XSHG', '')
                        search_query = f"{clean_ticker} 股票 公司 财报 新闻"
                        logger.debug(f"🇨🇳 [统一新闻工具] A股Google新闻搜索关键词: {search_query}")
                    else:
                        # 港股使用代码搜索
                        search_query = f"{ticker} 港股"
                        logger.debug(f"🇭🇰 [统一新闻工具] 港股Google新闻搜索关键词: {search_query}")

                    from app.data.core.interface import DataInterface
                    import asyncio as _asyncio
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
                    import asyncio as _asyncio
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

            logger.debug(f"📰 [统一新闻工具] 数据获取完成，总长度: {len(combined_result)}")
            return combined_result

        except Exception as e:
            error_msg = f"统一新闻工具执行失败: {str(e)}"
            logger.error(f"❌ [统一新闻工具] {error_msg}")
            return error_msg

    @staticmethod
    @tool
    @log_tool_call(tool_name="get_stock_sentiment_unified", log_args=True)
    def get_stock_sentiment_unified(
        ticker: Annotated[str, "股票代码（支持A股、港股、美股）"],
        curr_date: Annotated[str, "当前日期，格式：YYYY-MM-DD"]
    ) -> str:
        """
        统一的股票情绪分析工具
        自动识别股票类型（A股、港股、美股）并调用相应的情绪数据源

        Args:
            ticker: 股票代码（如：000001、0700.HK、AAPL）
            curr_date: 当前日期（格式：YYYY-MM-DD）

        Returns:
            str: 情绪分析报告
        """
        logger.debug(f"😊 [统一情绪工具] 分析股票: {ticker}")

        try:
            from app.utils.stock_utils import StockUtils

            # 自动识别股票类型
            market_info = StockUtils.get_market_info(ticker)
            is_china = market_info['is_china']
            is_hk = market_info['is_hk']
            is_us = market_info['is_us']

            logger.debug(f"😊 [统一情绪工具] 股票类型: {market_info['market_name']}")

            result_data = []

            if is_china or is_hk:
                # 中国A股和港股：使用社交媒体情绪分析
                logger.debug(f"🇨🇳🇭🇰 [统一情绪工具] 处理中文市场情绪...")

                try:
                    # 可以集成微博、雪球、东方财富等中文社交媒体情绪
                    # 目前使用基础的情绪分析
                    sentiment_summary = f"""
## 中文市场情绪分析

**股票**: {ticker} ({market_info['market_name']})
**分析日期**: {curr_date}

### 市场情绪概况
- 由于中文社交媒体情绪数据源暂未完全集成，当前提供基础分析
- 建议关注雪球、东方财富、同花顺等平台的讨论热度
- 港股市场还需关注香港本地财经媒体情绪

### 情绪指标
- 整体情绪: 中性
- 讨论热度: 待分析
- 投资者信心: 待评估

*注：完整的中文社交媒体情绪分析功能正在开发中*
"""
                    result_data.append(sentiment_summary)
                except Exception as e:
                    result_data.append(f"## 中文市场情绪\n获取失败: {e}")

            else:
                # 美股：使用Reddit情绪分析
                logger.debug(f"🇺🇸 [统一情绪工具] 处理美股情绪...")

                try:
                    sentiment_data = _get_us_news_sync(ticker)
                    result_data.append(f"## 美股Reddit情绪\n{sentiment_data}")
                except Exception as e:
                    result_data.append(f"## 美股Reddit情绪\n获取失败: {e}")

            # 组合所有数据
            combined_result = f"""# {ticker} 情绪分析

**股票类型**: {market_info['market_name']}
**分析日期**: {curr_date}

{chr(10).join(result_data)}

---
*数据来源: 根据股票类型自动选择最适合的情绪数据源*
"""

            logger.debug(f"😊 [统一情绪工具] 数据获取完成，总长度: {len(combined_result)}")
            return combined_result

        except Exception as e:
            error_msg = f"统一情绪分析工具执行失败: {str(e)}"
            logger.error(f"❌ [统一情绪工具] {error_msg}")
            return error_msg
