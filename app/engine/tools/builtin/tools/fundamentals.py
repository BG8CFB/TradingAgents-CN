"""
基本面工具 - 股票基本面财务数据、公司业绩数据

所有数据通过 DataInterface 统一获取，走 FallbackRouter 自动降级。
"""
import json
import logging
from typing import Optional
from datetime import datetime, timedelta

from app.utils.time_utils import now_utc, get_current_date, get_current_date_compact
from app.engine.tools.common.tool_result import success_result, no_data_result, error_result, format_tool_result, ErrorCodes
from app.engine.tools.common.format import format_result
from app.data.core.interface import DataInterface
from app.core.async_utils import run_async

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
        JSON 格式的 ToolResult
    """
    logger.info(f"[基本面工具] 分析股票: {stock_code}")
    start_time = now_utc()

    if not current_date:
        current_date = get_current_date()

    if not start_date:
        start_date = (now_utc() - timedelta(days=10)).strftime('%Y-%m-%d')

    if not end_date:
        end_date = current_date

    try:
        from app.utils.stock_utils import StockUtils

        market_info = StockUtils.get_market_info(stock_code)
        is_china = market_info['is_china']
        is_hk = market_info['is_hk']
        is_us = market_info['is_us']

        logger.info(f"[基本面工具] 股票类型: {market_info['market_name']}")

        result_data = []

        if is_china:
            logger.info("[基本面工具] 处理A股数据...")

            current_price_data = ""
            try:
                recent_end_date = current_date
                recent_start_date = (datetime.strptime(current_date, '%Y-%m-%d') - timedelta(days=2)).strftime('%Y-%m-%d')

                _di = DataInterface.get_instance()
                _r = run_async(_di.read("CN", "daily_quotes", symbol=stock_code,
                                          start_date=recent_start_date, end_date=recent_end_date))
                _d = _r.get("data")
                if _d:
                    import pandas as pd
                    if isinstance(_d, list) and _d:
                        current_price_data = pd.DataFrame(_d).to_string()
            except Exception as e:
                logger.error(f"[基本面工具] A股价格数据获取失败: {e}")
                current_price_data = ""

            try:
                from app.services.fundamentals import get_fundamentals_provider
                _fp = get_fundamentals_provider()
                fundamentals_raw = run_async(_fp.get_fundamentals(stock_code))
                if fundamentals_raw:
                    fundamentals_data = str(fundamentals_raw)
                else:
                    fundamentals_data = "暂无基本面数据"

                result_data.append(f"## A股基本面财务数据\n{fundamentals_data}")
            except Exception as e:
                logger.error(f"[基本面工具] A股基本面数据获取失败: {e}")
                result_data.append(f"## A股基本面财务数据\n获取失败: {e}")

        elif is_hk:
            logger.info("[基本面工具] 处理港股数据...")

            try:
                _di_info = DataInterface.get_instance()
                _r_info = run_async(_di_info.read("HK", "basic_info", symbol=stock_code))
                hk_info = _r_info.get("data")
                if isinstance(hk_info, list) and hk_info:
                    hk_info = hk_info[0]
                elif not hk_info:
                    hk_info = {}

                basic_info = f'''## 港股基础信息
**名称**: {hk_info.get('name', 'N/A')}
**行业**: {hk_info.get('industry', 'N/A')}
**市值**: {hk_info.get('market_cap', 'N/A')}
**市盈率(PE)**: {hk_info.get('pe', 'N/A')}
**周息率**: {hk_info.get('dividend_yield', 'N/A')}%
'''
                result_data.append(basic_info)
            except Exception as e:
                logger.error(f"[基本面工具] 港股基础信息获取失败: {e}")
                result_data.append(f"## 港股基础信息\n获取失败: {e}")

        else:
            logger.info("[基本面工具] 处理美股数据...")
            try:
                _di = DataInterface.get_instance()
                _r = run_async(_di.read("US", "financial_data", symbol=stock_code.upper()))
                us_info = _r.get("data")
                if us_info:
                    result_data.append(f"## 美股基本面信息\n{us_info}")
                else:
                    result_data.append("## 美股基本面信息\n暂无详细数据")
            except Exception as info_err:
                logger.warning(f"美股基本面信息获取失败: {info_err}")
                result_data.append(f"## 美股基本面信息\n获取失败: {info_err}")

        execution_time = (now_utc() - start_time).total_seconds()

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
    获取公司业绩数据（支持A股、港股、美股）

    自动识别股票市场类型，通过 DataInterface 统一获取。

    Args:
        stock_code: 股票代码，如 "000001.SZ"(A股)、"00700.HK"(港股)、"AAPL"(美股)
        data_type: 数据类型：forecast/express/indicators/income/balance/cashflow
        start_date: 开始日期，格式 YYYYMMDD 或 YYYY-MM-DD，默认 1 年前
        end_date: 结束日期，格式 YYYYMMDD 或 YYYY-MM-DD，默认今天
        period: 报告期，格式 YYYYMMDD，可选
        ind_name: 指标名称过滤，可选（仅港股有效）

    Returns:
        JSON 格式的 ToolResult
    """
    try:
        from app.utils.stock_utils import StockUtils

        market_info = StockUtils.get_market_info(stock_code)

        if market_info['is_china']:
            market = "CN"
            market_name = "A股"
        elif market_info['is_hk']:
            market = "HK"
            market_name = "港股"
        elif market_info['is_us']:
            market = "US"
            market_name = "美股"
            if ind_name:
                logger.warning(f"ind_name 参数仅对港股有效，美股 {stock_code} 将忽略此参数")
                ind_name = None
        else:
            return format_tool_result(error_result(
                ErrorCodes.UNKNOWN_MARKET,
                f"无法识别股票代码 {stock_code} 的市场类型",
                suggestion="检查股票代码格式是否正确"
            ))

        if not end_date:
            end_date = get_current_date_compact()
        if not start_date:
            start_date = (now_utc() - timedelta(days=360)).strftime('%Y%m%d')

        logger.info(f"[{market_name}业绩] 获取数据: {stock_code}, data_type: {data_type}")

        di = DataInterface.get_instance()
        result = run_async(di.read(market, "financial_data", symbol=stock_code,
                                     start_date=start_date, end_date=end_date))
        perf_data = result.get("data")
        if perf_data:
            import pandas as pd
            data = pd.DataFrame(perf_data) if isinstance(perf_data, list) else perf_data
            return format_tool_result(success_result(format_result(data, f"{stock_code} Performance ({market})")))

        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            f"无法获取{market_name}业绩数据: {stock_code}, data_type: {data_type}（请先同步 financial_data 数据）",
            suggestion="建议先同步对应市场的 financial_data 数据"
        ))

    except Exception as e:
        logger.error(f"get_company_performance_unified failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            str(e)
        ))


def get_stock_basic_info(
    stock_code: str,
) -> str:
    """
    获取股票基本信息。

    返回公司名称、行业分类、上市日期、注册资本等基本信息。

    Args:
        stock_code: 股票代码，如 "000001.SZ"(A股)、"AAPL"(美股)、"00700.HK"(港股)

    Returns:
        JSON 格式的 ToolResult
    """
    try:
        from app.utils.stock_utils import StockUtils

        market_info = StockUtils.get_market_info(stock_code)

        if market_info['is_china']:
            market = "CN"
            market_name = "A股"
            symbol = stock_code.replace('.SZ', '').replace('.SH', '').replace('.BJ', '') \
                               .replace('.sz', '').replace('.sh', '').replace('.bj', '')
        elif market_info['is_hk']:
            market = "HK"
            market_name = "港股"
            symbol = stock_code.replace('.HK', '').replace('.hk', '').zfill(5)
        elif market_info['is_us']:
            market = "US"
            market_name = "美股"
            symbol = stock_code.upper()
        else:
            return format_tool_result(error_result(
                ErrorCodes.UNKNOWN_MARKET,
                f"无法识别股票代码 {stock_code} 的市场类型",
            ))

        logger.info(f"[基本信息] 获取 {market_name} {stock_code} 基本信息数据")

        di = DataInterface.get_instance()
        result = run_async(di.read(market, "basic_info", symbol=symbol))
        data = result.get("data")

        if data:
            if isinstance(data, list):
                data = data[0] if data else None
            if data:
                return format_tool_result(success_result(
                    json.dumps(data, ensure_ascii=False, default=str)
                ))

        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            f"无法获取 {stock_code} 的基本信息（请先同步 basic_info 数据）",
        ))

    except Exception as e:
        logger.error(f"get_stock_basic_info failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            str(e)
        ))
