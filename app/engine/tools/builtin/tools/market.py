"""
市场行情工具 - 股票行情、分钟级数据、指数数据
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


def _to_json_str(data) -> str:
    """将 DataFrame 或其他类型转为 JSON 字符串"""
    import pandas as pd
    if isinstance(data, pd.DataFrame):
        return json.dumps(data.to_dict(orient='records'), ensure_ascii=False, default=str)
    return str(data)


def _normalize_symbol(symbol: str, market: str) -> str:
    """清洗 symbol，去掉交易所后缀以匹配数据库存储格式"""
    if market == "CN":
        return symbol.replace('.SZ', '').replace('.SH', '').replace('.BJ', '') \
                      .replace('.sz', '').replace('.sh', '').replace('.bj', '')
    elif market == "HK":
        return symbol.replace('.HK', '').replace('.hk', '').zfill(5)
    return symbol.upper()


def _read_daily_quotes(market: str, symbol: str, start_date: str, end_date: str):
    """统一读取日 K 线数据（CN/HK/US 共用）"""
    clean_symbol = _normalize_symbol(symbol, market)
    di = DataInterface.get_instance()
    result = run_async(di.read(market, "daily_quotes", symbol=clean_symbol,
                                  start_date=start_date, end_date=end_date))
    raw = result.get("data")
    if not raw:
        return None
    import pandas as pd
    return pd.DataFrame(raw) if isinstance(raw, list) and raw else raw


_MARKET_MAP = {
    "is_china": ("CN", "A股"),
    "is_hk": ("HK", "港股"),
    "is_us": ("US", "美股"),
}


def get_stock_data(
    stock_code: str,
    market_type: str = "cn",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """
    获取股票行情数据。

    返回开盘价、最高价、最低价、收盘价、成交量等行情数据。

    Args:
        stock_code: 股票代码，如 "000001.SZ"(A股)、"AAPL"(美股)、"00700.HK"(港股)
        market_type: 市场类型: "cn"(A股)、"us"(美股)、"hk"(港股)，默认自动推断
        start_date: 开始日期，格式 YYYY-MM-DD 或 YYYYMMDD，默认 1 个月前
        end_date: 结束日期，格式 YYYY-MM-DD 或 YYYYMMDD，默认今天

    Returns:
        JSON 格式的 ToolResult，包含 status、data、error_code、suggestion 字段
    """
    try:
        from app.utils.stock_utils import StockUtils

        market_info = StockUtils.get_market_info(stock_code)

        # 确定市场和名称
        market_key = None
        for attr, (mkt, name) in _MARKET_MAP.items():
            if market_info.get(attr):
                market_key = mkt
                break

        if not market_key:
            if market_type == "hk":
                market_key = "HK"
            elif market_type == "us":
                market_key = "US"
            else:
                market_key = "CN"

        if not start_date:
            start_date = (now_utc() - timedelta(days=30)).strftime('%Y-%m-%d')
        if not end_date:
            end_date = get_current_date()

        data = _read_daily_quotes(market_key, stock_code, start_date, end_date)

        if data is not None:
            return format_tool_result(success_result(_to_json_str(data)))
        else:
            return format_tool_result(error_result(
                ErrorCodes.UNKNOWN_MARKET,
                f"无法获取 {stock_code} 的行情数据",
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
        start_datetime: 开始时间，格式 YYYY-MM-DD HH:mm:ss，默认 1 天前
        end_datetime: 结束时间，格式 YYYY-MM-DD HH:mm:ss，默认现在
        freq: 频率，支持 "1min"、"5min"、"15min"、"30min"、"60min"，默认 "30min"

    Returns:
        JSON 格式的 ToolResult，包含 status、data、error_code、suggestion 字段
    """
    try:
        if not end_datetime:
            end_datetime = now_utc().strftime('%Y-%m-%d %H:%M:%S')
        if not start_datetime:
            start_datetime = (now_utc() - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')

        # 尝试通过 DataInterface 获取
        try:
            di = DataInterface.get_instance()
            clean_symbol = _normalize_symbol(stock_code, "CN")
            result = run_async(di.read("CN", "intraday_quotes", symbol=clean_symbol,
                                         start_date=start_datetime, end_date=end_datetime))
            intraday_data = result.get("data")
            if intraday_data:
                import pandas as pd
                data = pd.DataFrame(intraday_data) if isinstance(intraday_data, list) else intraday_data
                return format_tool_result(success_result(format_result(data, f"{stock_code} {freq} Data")))
        except Exception:
            pass

        # 回退到 AkShare
        if market_type == "cn":
            try:
                import akshare as ak
                import pandas as pd

                freq_map = {"1min": "1", "5min": "5", "15min": "15", "30min": "30", "60min": "60"}
                period = freq_map.get(freq, "30")

                code_6digit = stock_code.replace('.SH', '').replace('.SZ', '').replace('.sh', '').replace('.sz', '').zfill(6)

                logger.info(f"📊 尝试使用AkShare获取分钟级行情: {stock_code}, 频率: {freq}")

                df = ak.stock_zh_a_hist_min_em(symbol=code_6digit, period=period, adjust="")

                if df is not None and not df.empty:
                    logger.info(f"✅ AkShare成功获取分钟级行情: {stock_code}, {len(df)}条记录")

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

        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            f"无法获取分钟级行情数据: {stock_code}"
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
        if not end_date:
            end_date = get_current_date_compact()
        if not start_date:
            start_date = (now_utc() - timedelta(days=90)).strftime('%Y%m%d')

        try:
            di = DataInterface.get_instance()
            clean_symbol = _normalize_symbol(stock_code, "CN")
            result = run_async(di.read("CN", "market_quotes", symbol=clean_symbol,
                                         start_date=start_date, end_date=end_date))
            index_data = result.get("data")
            if index_data:
                import pandas as pd
                data = pd.DataFrame(index_data) if isinstance(index_data, list) else index_data
                return format_tool_result(success_result(format_result(data, f"Index: {stock_code}")))
        except Exception as e:
            logger.warning(f"DataInterface 获取指数数据失败: {e}")

        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            f"指数行情数据暂不可用: {stock_code}"
        ))
    except Exception as e:
        logger.error(f"get_index_data failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            str(e)
        ))
