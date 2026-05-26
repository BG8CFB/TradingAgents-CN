"""Toolkit 基本面类工具 — get_stock_fundamentals_unified。"""

from typing import Annotated

from langchain_core.tools import tool

from app.utils.logging_init import get_logger
from app.utils.tool_logging import log_tool_call
from app.utils.time_utils import now_utc, get_current_date

from .toolkit_helpers import _run_async, _get_stock_data_sync, _get_stock_info_sync

logger = get_logger("agents")


@tool
@log_tool_call(tool_name="get_stock_fundamentals_unified", log_args=True)
def get_stock_fundamentals_unified(
    ticker: Annotated[str, "股票代码（支持A股、港股、美股）"],
    start_date: Annotated[str, "开始日期，格式：YYYY-MM-DD"] = None,
    end_date: Annotated[str, "结束日期，格式：YYYY-MM-DD"] = None,
    curr_date: Annotated[str, "当前日期，格式：YYYY-MM-DD"] = None,
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

    logger.debug(
        f"🔍 [股票代码追踪] 统一基本面工具接收到的原始股票代码: '{ticker}' (类型: {type(ticker)})"
    )
    logger.debug(f"🔍 [股票代码追踪] 股票代码长度: {len(str(ticker))}")
    logger.debug(f"🔍 [股票代码追踪] 股票代码字符: {list(str(ticker))}")

    original_ticker = ticker

    try:
        from app.utils.stock_utils import StockUtils
        from datetime import datetime, timedelta

        # 自动识别股票类型
        market_info = StockUtils.get_market_info(ticker)
        is_china = market_info["is_china"]
        is_hk = market_info["is_hk"]
        is_us = market_info["is_us"]

        logger.debug(
            f"🔍 [股票代码追踪] StockUtils.get_market_info 返回的市场信息: {market_info}"
        )
        logger.info(
            f"📊 [统一基本面工具] 股票类型: {market_info['market_name']}"
        )
        logger.info(
            f"📊 [统一基本面工具] 货币: {market_info['currency_name']} ({market_info['currency_symbol']})"
        )

        if str(ticker) != str(original_ticker):
            logger.warning(
                f"🔍 [股票代码追踪] 警告：股票代码发生了变化！原始: '{original_ticker}' -> 当前: '{ticker}'"
            )

        if not curr_date:
            curr_date = get_current_date()

        if data_depth == "basic":
            analysis_modules = "basic"
            logger.debug(f"📊 [基本面策略] 快速分析模式：获取基础财务指标")
        elif data_depth == "standard":
            analysis_modules = "standard"
            logger.debug(f"📊 [基本面策略] 标准分析模式：获取标准财务分析")
        elif data_depth == "full":
            analysis_modules = "full"
            logger.debug(f"📊 [基本面策略] 深度分析模式：获取完整基本面分析")
        elif data_depth == "comprehensive":
            analysis_modules = "comprehensive"
            logger.debug(f"📊 [基本面策略] 全面分析模式：获取综合基本面分析")
        else:
            analysis_modules = "standard"
            logger.debug(f"📊 [基本面策略] 默认模式：获取标准基本面分析")

        days_to_fetch = 10
        days_to_analyze = 2

        logger.debug(
            f"📅 [基本面策略] 获取{days_to_fetch}天数据，分析最近{days_to_analyze}天"
        )

        if not start_date:
            start_date = (now_utc() - timedelta(days=days_to_fetch)).strftime(
                "%Y-%m-%d"
            )

        if not end_date:
            end_date = curr_date

        result_data = []

        if is_china:
            logger.debug(
                f"🇨🇳 [统一基本面工具] 处理A股数据，数据深度: {data_depth}..."
            )
            logger.debug(
                f"🔍 [股票代码追踪] 进入A股处理分支，ticker: '{ticker}'"
            )
            logger.debug(
                f"💡 [优化策略] 基本面分析只获取当前价格和财务数据，不获取历史日线数据"
            )

            try:
                from datetime import datetime, timedelta

                recent_end_date = curr_date
                recent_start_date = (
                    datetime.strptime(curr_date, "%Y-%m-%d") - timedelta(days=2)
                ).strftime("%Y-%m-%d")

                logger.debug(
                    f"🔍 [股票代码追踪] 调用 _get_stock_data_sync（仅获取最新价格），传入参数: market='CN', ticker='{ticker}', start_date='{recent_start_date}', end_date='{recent_end_date}'"
                )
                current_price_data = _get_stock_data_sync(
                    "CN", ticker, recent_start_date, recent_end_date
                )

                logger.debug(
                    f"🔍 [基本面工具调试] A股价格数据返回长度: {len(current_price_data)}"
                )
                logger.debug(
                    f"🔍 [基本面工具调试] A股价格数据前500字符:\n{current_price_data[:500]}"
                )

                result_data.append(f"## A股当前价格信息\n{current_price_data}")
            except Exception as e:
                logger.error(f"❌ [基本面工具调试] A股价格数据获取失败: {e}")
                result_data.append(f"## A股当前价格信息\n获取失败: {e}")
                current_price_data = ""

            try:
                from app.services.fundamentals import get_fundamentals_provider

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
            logger.debug(
                f"🇭🇰 [统一基本面工具] 处理港股数据，数据深度: {data_depth}..."
            )

            hk_data_success = False

            logger.debug(
                f"🔍 [港股基本面] 统一策略：获取完整数据（忽略 data_depth 参数）"
            )

            try:
                hk_data = _get_stock_data_sync("HK", ticker, start_date, end_date)

                logger.debug(
                    f"🔍 [基本面工具调试] 港股数据返回长度: {len(hk_data)}"
                )
                logger.debug(
                    f"🔍 [基本面工具调试] 港股数据前500字符:\n{hk_data[:500]}"
                )

                if hk_data and len(hk_data) > 100 and "❌" not in hk_data:
                    result_data.append(f"## 港股数据\n{hk_data}")
                    hk_data_success = True
                    logger.debug(
                        f"✅ [统一基本面工具] 港股主要数据源成功"
                    )
                else:
                    logger.warning(
                        f"⚠️ [统一基本面工具] 港股主要数据源质量不佳"
                    )

            except Exception as e:
                logger.error(f"❌ [基本面工具调试] 港股数据获取失败: {e}")

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
                    logger.debug(
                        f"✅ [统一基本面工具] 港股备用信息成功"
                    )

                except Exception as e2:
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
                    logger.error(
                        f"❌ [统一基本面工具] 港股所有数据源都失败: {e2}"
                    )

        else:
            logger.debug(f"🇺🇸 [统一基本面工具] 处理美股数据...")

            logger.debug(
                f"🔍 [美股基本面] 统一策略：获取完整数据（忽略 data_depth 参数）"
            )

            try:
                from app.data.core.interface import DataInterface

                _di = DataInterface.get_instance()
                _r = _run_async(
                    _di.read("US", "financial_data", symbol=ticker.upper())
                )
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

        logger.debug(
            f"📊 [统一基本面工具] ===== 数据获取完成摘要 ====="
        )
        logger.debug(f"📊 [统一基本面工具] 股票代码: {ticker}")
        logger.info(
            f"📊 [统一基本面工具] 股票类型: {market_info['market_name']}"
        )
        logger.debug(f"📊 [统一基本面工具] 数据深度级别: {data_depth}")
        logger.debug(
            f"📊 [统一基本面工具] 获取的数据模块数量: {len(result_data)}"
        )
        logger.info(
            f"📊 [统一基本面工具] 总数据长度: {len(combined_result)} 字符"
        )

        for i, data_section in enumerate(result_data, 1):
            section_lines = data_section.split("\n")
            section_title = section_lines[0] if section_lines else "未知模块"
            section_length = len(data_section)
            logger.debug(
                f"📊 [统一基本面工具] 数据模块 {i}: {section_title} ({section_length} 字符)"
            )

            if "获取失败" in data_section or "❌" in data_section:
                logger.warning(
                    f"⚠️ [统一基本面工具] 数据模块 {i} 包含错误信息"
                )
            else:
                logger.debug(
                    f"✅ [统一基本面工具] 数据模块 {i} 获取成功"
                )

        if data_depth in ["basic", "standard"]:
            logger.info(
                f"📊 [统一基本面工具] 基础/标准级别策略: 仅获取核心价格数据和基础信息"
            )
        elif data_depth in ["full", "detailed", "comprehensive"]:
            logger.debug(
                f"📊 [统一基本面工具] 完整/详细/全面级别策略: 获取价格数据 + 基本面数据"
            )
        else:
            logger.info(f"📊 [统一基本面工具] 默认策略: 获取完整数据")

        logger.debug(
            f"📊 [统一基本面工具] ===== 数据获取摘要结束 ====="
        )

        return combined_result

    except Exception as e:
        error_msg = f"统一基本面分析工具执行失败: {str(e)}"
        logger.error(f"❌ [统一基本面工具] {error_msg}")
        return error_msg
