"""Toolkit 市场类工具 — get_china_market_overview, get_stock_market_data_unified。"""

from typing import Annotated

from langchain_core.tools import tool

from app.utils.logging_init import get_logger
from app.utils.tool_logging import log_tool_call

from .toolkit_helpers import _run_async, _get_stock_data_sync

logger = get_logger("agents")


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
        indices_map = {}
        for idx_code, idx_name in [
            ("000001", "上证指数"),
            ("399001", "深证成指"),
            ("399006", "创业板指"),
        ]:
            try:
                from app.data.core.interface import DataInterface

                di = DataInterface.get_instance()
                r = _run_async(di.read("CN", "market_quotes", symbol=idx_code))
                d = r.get("data")
                if d:
                    doc = d[0] if isinstance(d, list) and d else d
                    indices_map[idx_name] = (
                        f"{doc.get('close', 'N/A')} ({doc.get('pct_chg', 'N/A')}%)"
                    )
            except Exception as e:
                logger.debug(f"获取指数数据失败: {idx_name}: {e}")
                indices_map[idx_name] = "数据获取中..."

        indices_lines = "\n".join(
            [f"- {k}: {v}" for k, v in indices_map.items()]
        )

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


@tool
@log_tool_call(tool_name="get_stock_market_data_unified", log_args=True)
def get_stock_market_data_unified(
    ticker: Annotated[str, "股票代码（支持A股、港股、美股）"],
    start_date: Annotated[
        str,
        "开始日期，格式：YYYY-MM-DD。注意：系统会自动扩展到配置的回溯天数（通常为365天），你只需要传递分析日期即可",
    ],
    end_date: Annotated[
        str,
        "结束日期，格式：YYYY-MM-DD。通常与start_date相同，传递当前分析日期即可",
    ],
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
        is_china = market_info["is_china"]
        is_hk = market_info["is_hk"]
        market_info["is_us"]

        logger.debug(f"📈 [统一市场工具] 股票类型: {market_info['market_name']}")
        logger.debug(
            f"📈 [统一市场工具] 货币: {market_info['currency_name']} ({market_info['currency_symbol']}"
        )

        result_data = []

        if is_china:
            logger.info("🇨🇳 [统一市场工具] 处理A股市场数据...")

            try:
                stock_data = _get_stock_data_sync("CN", ticker, start_date, end_date)

                logger.debug(f"🔍 [市场工具调试] A股数据返回长度: {len(stock_data)}")
                logger.debug(
                    f"🔍 [市场工具调试] A股数据前500字符:\n{stock_data[:500]}"
                )

                result_data.append(f"## A股市场数据\n{stock_data}")
            except Exception as e:
                logger.error(f"❌ [市场工具调试] A股数据获取失败: {e}")
                result_data.append(f"## A股市场数据\n获取失败: {e}")

        elif is_hk:
            logger.info("🇭🇰 [统一市场工具] 处理港股市场数据...")

            try:
                hk_data = _get_stock_data_sync("HK", ticker, start_date, end_date)

                logger.debug(f"🔍 [市场工具调试] 港股数据返回长度: {len(hk_data)}")
                logger.debug(
                    f"🔍 [市场工具调试] 港股数据前500字符:\n{hk_data[:500]}"
                )

                result_data.append(f"## 港股市场数据\n{hk_data}")
            except Exception as e:
                logger.error(f"❌ [市场工具调试] 港股数据获取失败: {e}")
                result_data.append(f"## 港股市场数据\n获取失败: {e}")

        else:
            logger.debug("🇺🇸 [统一市场工具] 处理美股市场数据...")

            try:
                from app.data.core.interface import DataInterface

                _di = DataInterface.get_instance()
                _r = _run_async(
                    _di.read(
                        "US",
                        "daily_quotes",
                        symbol=ticker.upper(),
                        start_date=start_date,
                        end_date=end_date,
                    )
                )
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

        logger.debug(
            f"📈 [统一市场工具] 数据获取完成，总长度: {len(combined_result)}"
        )
        return combined_result

    except Exception as e:
        error_msg = f"统一市场数据工具执行失败: {str(e)}"
        logger.error(f"❌ [统一市场工具] {error_msg}")
        return error_msg
