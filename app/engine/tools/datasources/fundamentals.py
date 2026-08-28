"""
基本面工具 - 股票基本面财务数据、公司业绩数据

所有数据通过 DataInterface 统一获取，走 FallbackRouter 自动降级。
"""

import json
import logging
from typing import Optional
from datetime import timedelta

from app.utils.time_utils import now_utc, get_current_date, get_current_date_compact
from app.engine.tools.common.tool_result import success_result, error_result, format_tool_result, ErrorCodes
from app.engine.tools.common.format import format_result
from app.engine.tools.common.data_access import read_with_refresh

logger = logging.getLogger(__name__)


def get_stock_fundamentals(
    stock_code: str, current_date: str = None, start_date: str = None, end_date: str = None
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
        start_date = (now_utc() - timedelta(days=10)).strftime("%Y-%m-%d")

    if not end_date:
        end_date = current_date

    try:
        from app.utils.stock_utils import StockUtils

        market_info = StockUtils.get_market_info(stock_code)
        is_china = market_info["is_china"]
        is_hk = market_info["is_hk"]
        market_info["is_us"]

        logger.info(f"[基本面工具] 股票类型: {market_info['market_name']}")

        result_data = []

        if is_china:
            logger.info("[基本面工具] 处理A股数据...")

            try:
                # 直接读标准库 financial_data 域，库空时按需刷新后重读
                clean_symbol = (
                    stock_code.replace(".SZ", "")
                    .replace(".SH", "")
                    .replace(".BJ", "")
                    .replace(".sz", "")
                    .replace(".sh", "")
                    .replace(".bj", "")
                )
                fundamentals_raw = read_with_refresh("CN", "financial_data", symbol=clean_symbol)
                _d = fundamentals_raw.get("data") if fundamentals_raw else None
                if _d:
                    import pandas as pd

                    # 选取标准 schema 中的核心字段，避免把整条原始记录透传给 LLM
                    _CORE_FIELDS = [
                        "report_period",
                        "statement_type",
                        "revenue",
                        "net_profit",
                        "total_assets",
                        "total_equity",
                        "roe",
                        "roa",
                        "gross_margin",
                        "net_margin",
                        "eps",
                        "bps",
                        "debt_ratio",
                        "current_ratio",
                        "announce_date",
                        "data_source",
                    ]
                    records = _d if isinstance(_d, list) else [_d]
                    df = pd.DataFrame(records)
                    cols = [c for c in _CORE_FIELDS if c in df.columns]
                    df = df[cols]
                    result_data.append(f"## A股基本面财务数据\n{format_result(df, 'A股财务数据 (标准 financial_data 域)')}")
                else:
                    result_data.append("## A股基本面财务数据\n暂无基本面数据（请先同步 financial_data 数据）")
            except Exception as e:
                logger.error(f"[基本面工具] A股基本面数据获取失败: {e}")
                result_data.append(f"## A股基本面财务数据\n获取失败: {e}")

        elif is_hk:
            logger.info("[基本面工具] 处理港股数据...")

            try:
                _r_info = read_with_refresh("HK", "basic_info", symbol=stock_code)
                hk_info = _r_info.get("data") if _r_info else None
                if isinstance(hk_info, list) and hk_info:
                    hk_info = hk_info[0]
                elif not hk_info:
                    hk_info = {}

                basic_info = f"""## 港股基础信息
**名称**: {hk_info.get("name", "N/A")}
**行业**: {hk_info.get("industry", "N/A")}
**市值**: {hk_info.get("market_cap", "N/A")}
**市盈率(PE)**: {hk_info.get("pe", "N/A")}
**周息率**: {hk_info.get("dividend_yield", "N/A")}%
"""
                result_data.append(basic_info)
            except Exception as e:
                logger.error(f"[基本面工具] 港股基础信息获取失败: {e}")
                result_data.append(f"## 港股基础信息\n获取失败: {e}")

        else:
            logger.info("[基本面工具] 处理美股数据...")
            try:
                _r = read_with_refresh("US", "financial_data", symbol=stock_code.upper())
                us_info = _r.get("data") if _r else None
                if us_info:
                    import pandas as pd

                    records = us_info if isinstance(us_info, list) else [us_info]
                    result_data.append(
                        f"## 美股基本面信息\n{format_result(pd.DataFrame(records), '美股财务数据 (标准 financial_data 域)')}"
                    )
                else:
                    result_data.append("## 美股基本面信息\n暂无详细数据")
            except Exception as info_err:
                logger.warning(f"美股基本面信息获取失败: {info_err}")
                result_data.append(f"## 美股基本面信息\n获取失败: {info_err}")

        execution_time = (now_utc() - start_time).total_seconds()

        combined_result = f"""# {stock_code} 基本面分析

**股票类型**: {market_info["market_name"]}
**分析日期**: {current_date}
**执行时间**: {execution_time:.2f}秒

{chr(10).join(result_data)}
"""
        return format_tool_result(success_result(combined_result))

    except Exception as e:
        logger.error(f"get_stock_fundamentals failed: {e}")
        return format_tool_result(error_result(ErrorCodes.DATA_FETCH_ERROR, str(e)))


def get_company_performance_unified(
    stock_code: str,
    data_type: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    period: Optional[str] = None,
    ind_name: Optional[str] = None,
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

        if market_info["is_china"]:
            market = "CN"
            market_name = "A股"
        elif market_info["is_hk"]:
            market = "HK"
            market_name = "港股"
        elif market_info["is_us"]:
            market = "US"
            market_name = "美股"
            if ind_name:
                logger.warning(f"ind_name 参数仅对港股有效，美股 {stock_code} 将忽略此参数")
                ind_name = None
        else:
            return format_tool_result(
                error_result(
                    ErrorCodes.UNKNOWN_MARKET,
                    f"无法识别股票代码 {stock_code} 的市场类型",
                    suggestion="检查股票代码格式是否正确",
                )
            )

        # 清洗 symbol（去掉交易所后缀以匹配数据库存储格式）
        if market_info["is_china"]:
            symbol = (
                stock_code.replace(".SZ", "")
                .replace(".SH", "")
                .replace(".BJ", "")
                .replace(".sz", "")
                .replace(".sh", "")
                .replace(".bj", "")
            )
        elif market_info["is_hk"]:
            symbol = stock_code.replace(".HK", "").replace(".hk", "").zfill(5)
        else:
            symbol = stock_code.upper()

        if not end_date:
            end_date = get_current_date_compact()
        if not start_date:
            start_date = (now_utc() - timedelta(days=360)).strftime("%Y%m%d")

        logger.info(f"[{market_name}业绩] 获取数据: {stock_code}, data_type: {data_type}")

        # data_type → statement_type 映射（API 层用 indicators，数据库存 indicator）
        _DT_TO_STMT = {
            "forecast": None,
            "express": None,
            "indicators": "indicator",
            "income": "income",
            "balance": "balance",
            "cashflow": "cashflow",
        }
        stmt_type = _DT_TO_STMT.get(data_type)

        result = read_with_refresh(
            market,
            "financial_data",
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            filters={"statement_type": stmt_type} if stmt_type else None,
        )
        perf_data = result.get("data") if result else None
        if perf_data:
            import pandas as pd

            data = pd.DataFrame(perf_data) if isinstance(perf_data, list) else perf_data
            return format_tool_result(success_result(format_result(data, f"{stock_code} Performance ({market})")))

        return format_tool_result(
            error_result(
                ErrorCodes.DATA_FETCH_ERROR,
                f"无法获取{market_name}业绩数据: {stock_code}, data_type: {data_type}（请先同步 financial_data 数据）",
                suggestion="建议先同步对应市场的 financial_data 数据",
            )
        )

    except Exception as e:
        logger.error(f"get_company_performance_unified failed: {e}")
        return format_tool_result(error_result(ErrorCodes.DATA_FETCH_ERROR, str(e)))


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

        if market_info["is_china"]:
            market = "CN"
            market_name = "A股"
            symbol = (
                stock_code.replace(".SZ", "")
                .replace(".SH", "")
                .replace(".BJ", "")
                .replace(".sz", "")
                .replace(".sh", "")
                .replace(".bj", "")
            )
        elif market_info["is_hk"]:
            market = "HK"
            market_name = "港股"
            symbol = stock_code.replace(".HK", "").replace(".hk", "").zfill(5)
        elif market_info["is_us"]:
            market = "US"
            market_name = "美股"
            symbol = stock_code.upper()
        else:
            return format_tool_result(
                error_result(
                    ErrorCodes.UNKNOWN_MARKET,
                    f"无法识别股票代码 {stock_code} 的市场类型",
                )
            )

        logger.info(f"[基本信息] 获取 {market_name} {stock_code} 基本信息数据")

        result = read_with_refresh(market, "basic_info", symbol=symbol)
        data = result.get("data") if result else None

        if data:
            if isinstance(data, list):
                data = data[0] if data else None
            if data:
                return format_tool_result(success_result(json.dumps(data, ensure_ascii=False, default=str)))

        return format_tool_result(
            error_result(
                ErrorCodes.DATA_FETCH_ERROR,
                f"无法获取 {stock_code} 的基本信息（请先同步 basic_info 数据）",
            )
        )

    except Exception as e:
        logger.error(f"get_stock_basic_info failed: {e}")
        return format_tool_result(error_result(ErrorCodes.DATA_FETCH_ERROR, str(e)))
