"""
市场行情工具 - 股票行情、分钟级数据、指数数据
"""
import json
import logging
from typing import Optional
from datetime import datetime, timedelta

from app.utils.time_utils import now_utc, get_current_date, get_current_date_compact
from app.engine.tools.builtin.standard import success_result, no_data_result, error_result, format_tool_result, ErrorCodes
from app.engine.tools.builtin.helpers import get_manager, format_result

logger = logging.getLogger(__name__)


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

            return format_tool_result(success_result(data_str))
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
                return format_tool_result(success_result(format_result(data, f"{stock_code} {freq} Data")))
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
        return format_tool_result(success_result(format_result(data, f"Index: {stock_code}")))
    except Exception as e:
        logger.error(f"get_index_data failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            str(e)
        ))


# --- 元数据 ---

TOOL_FUNCTIONS = [get_stock_data, get_stock_data_minutes, get_index_data]
DATA_SOURCE_MAP = {
    "get_stock_data": ["tushare", "akshare"],
    "get_stock_data_minutes": ["tushare", "akshare"],
    "get_index_data": ["tushare", "akshare"],
}
ANALYST_MAP = {
    "get_stock_data": ["market-analyst", "china-market-analyst", "fundamentals-analyst"],
    "get_stock_data_minutes": ["market-analyst", "short-term-capital-analyst"],
    "get_index_data": ["china-market-analyst", "market-analyst"],
}
