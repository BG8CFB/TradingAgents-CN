"""
基本面工具 - 股票基本面财务数据、公司业绩数据
"""
import json
import logging
import os
from typing import Optional
from datetime import datetime, timedelta

from app.utils.time_utils import now_utc, get_current_date, get_current_date_compact
from app.engine.tools.builtin.standard import success_result, no_data_result, error_result, format_tool_result, ErrorCodes
from app.engine.tools.builtin.helpers import get_manager, format_result

logger = logging.getLogger(__name__)


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
                return format_tool_result(success_result(format_result(data, f"{stock_code} Performance ({market.upper()})")))
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
                            result_text += format_result(df_filtered, f"{stock_code} Forecast (AkShare)")

                            return format_tool_result(success_result(result_text))

                elif market == "hk":
                    # 港股业绩预测
                    code_clean = stock_code.replace('.HK', '').replace('.hk', '').zfill(5)
                    df = ak.stock_hk_profit_forecast_et(symbol=code_clean)

                    if df is not None and not df.empty:
                        logger.info(f"✅ AkShare成功获取港股业绩预告: {stock_code}, {len(df)}条记录")

                        # 格式化输出
                        result_text = f"# {stock_code} 港股业绩预告（来源：AkShare-东方财富）\n\n"
                        result_text += format_result(df, f"{stock_code} Forecast (AkShare)")

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


# --- 元数据 ---

TOOL_FUNCTIONS = [get_stock_fundamentals, get_company_performance_unified]
DATA_SOURCE_MAP = {
    "get_stock_fundamentals": ["tushare", "akshare"],
    "get_company_performance_unified": ["tushare", "akshare"],
}
ANALYST_MAP = {
    "get_stock_fundamentals": ["fundamentals-analyst"],
    "get_company_performance_unified": ["fundamentals-analyst"],
}
