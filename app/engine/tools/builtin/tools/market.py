"""
市场行情工具 - 股票行情、分钟级数据、指数数据

所有数据通过 DataInterface 统一获取，走 FallbackRouter 自动降级。
"""
import json
import logging
from typing import Optional
from datetime import timedelta, date, datetime

from app.utils.time_utils import now_utc, get_current_date, get_current_date_compact
from app.data.core.market import get_latest_trade_day, to_market_time
from app.engine.tools.common.tool_result import success_result, error_result, format_tool_result, ErrorCodes
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


async def _read_recent_trading_day_records(domain: str, symbol: str, recent_days: int = 30):
    """读取某域记录：优先取最近交易日精确查，否则回退到最近 N 天范围内的最新记录。

    用于 price_limit / chip_distribution 等按交易日落库的域：若直接查“今天”
    （周末/休市）会返回空导致“获取失败”。这里回退到最近一个交易日 / 最近 N 天。
    """
    di = DataInterface.get_instance()
    try:
        td = await get_latest_trade_day("CN")
    except Exception:
        td = None
    if td:
        td_s = td.strftime("%Y%m%d")
        r = await di.read("CN", domain, symbol=symbol, start_date=td_s, end_date=td_s)
        if r.get("data"):
            return r
    end = date.today()
    start = end - timedelta(days=recent_days)
    return await di.read("CN", domain, symbol=symbol,
                         start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"))


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
        JSON 格式的 ToolResult
    """
    try:
        from app.utils.stock_utils import StockUtils

        market_info = StockUtils.get_market_info(stock_code)

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
                f"无法获取 {stock_code} 的行情数据（请先同步 daily_quotes 数据）",
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
        JSON 格式的 ToolResult
    """
    try:
        if not end_datetime:
            end_datetime = to_market_time(now_utc(), "CN").strftime('%Y-%m-%d %H:%M:%S')
        if not start_datetime:
            # 锚定到最近一个交易日往前 30 天（而非“现在往前 1 天”），
            # 避免周末查询窗口落空，同时兼容分钟线同步滞后（可能停留在数日前）。
            latest = run_async(get_latest_trade_day("CN")) or date.today()
            start_date = latest - timedelta(days=30)
            start_datetime = datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0).strftime(
                '%Y-%m-%d %H:%M:%S'
            )

        di = DataInterface.get_instance()
        clean_symbol = _normalize_symbol(stock_code, "CN")
        result = run_async(di.read("CN", "intraday_quotes", symbol=clean_symbol,
                                     start_date=start_datetime, end_date=end_datetime,
                                     filters={"freq": freq}))
        intraday_data = result.get("data")
        if intraday_data:
            import pandas as pd
            if isinstance(intraday_data, list) and intraday_data:
                # 仅保留最新一个交易日，控制输出体积（窗口可能覆盖多日）
                days = sorted(
                    {str(r.get("datetime", "")).split(" ")[0] for r in intraday_data if r.get("datetime")}
                )
                if days:
                    latest_day = days[-1]
                    intraday_data = [r for r in intraday_data if str(r.get("datetime", "")).startswith(latest_day)]
            data = pd.DataFrame(intraday_data) if isinstance(intraday_data, list) else intraday_data
            return format_tool_result(success_result(format_result(data, f"{stock_code} {freq} Data")))

        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            f"无法获取分钟级行情数据: {stock_code}（请先同步 intraday_quotes 数据）"
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
        JSON 格式的 ToolResult
    """
    try:
        from app.utils.stock_utils import StockUtils

        if not end_date:
            end_date = get_current_date_compact()
        if not start_date:
            start_date = (now_utc() - timedelta(days=90)).strftime('%Y%m%d')

        # 动态推导市场
        market_info = StockUtils.get_market_info(stock_code)
        market = "CN"
        for attr, (mkt, _) in _MARKET_MAP.items():
            if market_info.get(attr):
                market = mkt
                break

        di = DataInterface.get_instance()
        clean_symbol = _normalize_symbol(stock_code, market)
        result = run_async(di.read(market, "market_quotes", symbol=clean_symbol,
                                     start_date=start_date, end_date=end_date))
        index_data = result.get("data")
        if index_data:
            import pandas as pd
            data = pd.DataFrame(index_data) if isinstance(index_data, list) else index_data
            return format_tool_result(success_result(format_result(data, f"Index: {stock_code}")))

        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            f"指数行情数据暂不可用: {stock_code}（请先同步 market_quotes 数据）"
        ))
    except Exception as e:
        logger.error(f"get_index_data failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            str(e)
        ))


def get_stock_indicators(
    stock_code: str,
    market_type: str = "cn",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """
    获取股票估值指标数据。

    返回 PE、PB、PS、总市值、流通市值、换手率等每日估值指标。

    Args:
        stock_code: 股票代码，如 "000001.SZ"(A股)、"AAPL"(美股)、"00700.HK"(港股)
        market_type: 市场类型: "cn"(A股)、"us"(美股)、"hk"(港股)，默认自动推断
        start_date: 开始日期，格式 YYYY-MM-DD 或 YYYYMMDD，默认 1 个月前
        end_date: 结束日期，格式 YYYY-MM-DD 或 YYYYMMDD，默认今天

    Returns:
        JSON 格式的 ToolResult
    """
    try:
        from app.utils.stock_utils import StockUtils

        market_info = StockUtils.get_market_info(stock_code)

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

        clean_symbol = _normalize_symbol(stock_code, market_key)
        di = DataInterface.get_instance()
        result = run_async(di.read(market_key, "daily_indicators", symbol=clean_symbol,
                                    start_date=start_date, end_date=end_date))
        raw = result.get("data")

        if raw:
            import pandas as pd
            data = pd.DataFrame(raw) if isinstance(raw, list) and raw else raw
            return format_tool_result(success_result(format_result(data, f"{stock_code} Indicators")))

        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            f"无法获取 {stock_code} 的估值指标数据（请先同步 daily_indicators 数据）",
        ))

    except Exception as e:
        logger.error(f"get_stock_indicators failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            str(e)
        ))


def get_stock_technical_indicators(
    stock_code: str,
    market_type: str = "cn",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """
    获取股票技术指标数据（MA/MACD/RSI/KDJ/布林带）。

    从日线行情数据计算技术指标，供市场技术分析师使用。

    Args:
        stock_code: 股票代码
        market_type: 市场类型
        start_date: 开始日期，默认90天前
        end_date: 结束日期，默认今天

    Returns:
        JSON 格式的技术指标数据
    """
    try:
        from app.utils.stock_utils import StockUtils
        from app.utils.indicators import add_all_indicators

        market_info = StockUtils.get_market_info(stock_code)
        market_key = None
        for attr, (mkt, name) in _MARKET_MAP.items():
            if market_info.get(attr):
                market_key = mkt
                break
        if not market_key:
            market_key = "CN" if market_type != "hk" and market_type != "us" else market_type.upper()

        if not start_date:
            start_date = (now_utc() - timedelta(days=90)).strftime('%Y-%m-%d')
        if not end_date:
            end_date = get_current_date()

        data = _read_daily_quotes(market_key, stock_code, start_date, end_date)
        if data is None or data.empty:
            return format_tool_result(error_result(
                ErrorCodes.DATA_FETCH_ERROR,
                f"无法获取 {stock_code} 的行情数据，无法计算技术指标",
                suggestion="请先同步 daily_quotes 数据"
            ))

        # 确保按日期排序
        if 'trade_date' in data.columns:
            data = data.sort_values('trade_date').reset_index(drop=True)

        # 计算技术指标
        data = add_all_indicators(data, rsi_style='china')

        # 只返回最近10个交易日的指标数据（精简输出）
        recent = data.tail(10).copy()

        # 选择指标列
        indicator_cols = ['trade_date', 'open', 'high', 'low', 'close', 'volume',
                         'ma5', 'ma10', 'ma20', 'ma60',
                         'rsi6', 'rsi12', 'rsi24', 'rsi14',
                         'macd_dif', 'macd_dea', 'macd',
                         'boll_mid', 'boll_upper', 'boll_lower',
                         'kdj_k', 'kdj_d', 'kdj_j', 'williams_r']
        available_cols = [c for c in indicator_cols if c in recent.columns]
        result_data = recent[available_cols]

        return format_tool_result(success_result(
            format_result(result_data, f"{stock_code} 技术指标")
        ))

    except Exception as e:
        logger.error(f"get_stock_technical_indicators failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            f"计算技术指标失败: {str(e)}"
        ))


def get_trading_status(
    stock_code: str,
    trade_date: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """获取停复牌信息。"""
    try:
        if not end_date:
            end_date = get_current_date_compact()
        if not start_date:
            start_date = (now_utc() - timedelta(days=30)).strftime('%Y%m%d')
        symbol = stock_code.replace('.SZ', '').replace('.SH', '').replace('.BJ', '') \
                           .replace('.sz', '').replace('.sh', '').replace('.bj', '').zfill(6)
        di = DataInterface.get_instance()
        result = run_async(di.read("CN", "trading_status", symbol=symbol,
                                     start_date=start_date, end_date=end_date))
        data = result.get("data")
        if data:
            import pandas as pd
            df = pd.DataFrame(data) if isinstance(data, list) else data
            return format_tool_result(success_result(format_result(df, f"停复牌: {stock_code}")))
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR, f"{stock_code} 无停复牌信息",
            suggestion="请先同步停复牌数据"
        ))
    except Exception as e:
        logger.error(f"get_trading_status failed: {e}")
        return format_tool_result(error_result(ErrorCodes.DATA_FETCH_ERROR, str(e)))


def get_price_limit(
    stock_code: str,
    trade_date: Optional[str] = None,
) -> str:
    """获取涨跌停价格数据。

    未指定 trade_date 时优先取最近交易日；若仍为空，回退到最近 30 天范围内
    的最新一条，避免在非交易日（周末/休市）直接查当日导致“获取失败”。
    """
    try:
        symbol = stock_code.replace('.SZ', '').replace('.SH', '').replace('.BJ', '') \
                           .replace('.sz', '').replace('.sh', '').replace('.bj', '').zfill(6)
        di = DataInterface.get_instance()
        if trade_date:
            td = str(trade_date).replace("-", "")
            result = run_async(di.read("CN", "price_limit", symbol=symbol,
                                       start_date=td, end_date=td))
        else:
            result = run_async(_read_recent_trading_day_records("price_limit", symbol))
        data = result.get("data")
        if data:
            import pandas as pd
            if isinstance(data, list):
                data = sorted(data, key=lambda x: str(x.get("trade_date", "")), reverse=True)[:1]
            df = pd.DataFrame(data) if isinstance(data, list) else data
            return format_tool_result(success_result(format_result(df, f"涨跌停价格: {stock_code}")))
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR, f"{stock_code} 无涨跌停数据",
            suggestion="请先同步涨跌停价格数据"
        ))
    except Exception as e:
        logger.error(f"get_price_limit failed: {e}")
        return format_tool_result(error_result(ErrorCodes.DATA_FETCH_ERROR, str(e)))


def get_index_daily_data(
    stock_code: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """获取指数日线行情数据。"""
    try:
        if not end_date:
            end_date = get_current_date_compact()
        if not start_date:
            start_date = (now_utc() - timedelta(days=90)).strftime('%Y%m%d')
        di = DataInterface.get_instance()
        clean_symbol = _normalize_symbol(stock_code, "CN")
        result = run_async(di.read("CN", "index_data", symbol=clean_symbol,
                                     start_date=start_date, end_date=end_date))
        data = result.get("data")
        if data:
            import pandas as pd
            df = pd.DataFrame(data) if isinstance(data, list) else data
            return format_tool_result(success_result(format_result(df, f"指数行情: {stock_code}")))
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR, f"无法获取 {stock_code} 指数数据",
            suggestion="请先同步指数行情数据"
        ))
    except Exception as e:
        logger.error(f"get_index_daily_data failed: {e}")
        return format_tool_result(error_result(ErrorCodes.DATA_FETCH_ERROR, str(e)))


def get_chip_distribution(
    stock_code: str,
    trade_date: Optional[str] = None,
) -> str:
    """获取筹码分布数据。

    未指定 trade_date 时优先取最近交易日；若仍为空，回退到最近 30 天范围内
    的最新一条，避免在非交易日（周末/休市）直接查当日导致“无筹码数据”。
    """
    try:
        symbol = stock_code.replace('.SZ', '').replace('.SH', '').replace('.BJ', '') \
                           .replace('.sz', '').replace('.sh', '').replace('.bj', '').zfill(6)
        di = DataInterface.get_instance()
        if trade_date:
            td = str(trade_date).replace("-", "")
            result = run_async(di.read("CN", "chip_distribution", symbol=symbol,
                                       start_date=td, end_date=td))
        else:
            result = run_async(_read_recent_trading_day_records("chip_distribution", symbol))
        data = result.get("data")
        if data:
            import pandas as pd
            if isinstance(data, list):
                data = sorted(data, key=lambda x: str(x.get("trade_date", "")), reverse=True)[:1]
            df = pd.DataFrame(data) if isinstance(data, list) else data
            return format_tool_result(success_result(format_result(df, f"筹码分布: {stock_code}")))
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR, f"{stock_code} 无筹码数据",
            suggestion="请先同步筹码分布数据"
        ))
    except Exception as e:
        logger.error(f"get_chip_distribution failed: {e}")
        return format_tool_result(error_result(ErrorCodes.DATA_FETCH_ERROR, str(e)))


def get_adj_factors(
    stock_code: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """获取复权因子数据（前/后复权比例，用于精确收益计算）。"""
    try:
        if not end_date:
            end_date = get_current_date_compact()
        if not start_date:
            start_date = (now_utc() - timedelta(days=90)).strftime('%Y%m%d')
        symbol = stock_code.replace('.SZ', '').replace('.SH', '').replace('.BJ', '') \
                           .replace('.sz', '').replace('.sh', '').replace('.bj', '').zfill(6)
        di = DataInterface.get_instance()
        result = run_async(di.read("CN", "adj_factors", symbol=symbol,
                                   start_date=start_date, end_date=end_date))
        data = result.get("data")
        if data:
            import pandas as pd
            df = pd.DataFrame(data) if isinstance(data, list) else data
            return format_tool_result(success_result(format_result(df, f"复权因子: {stock_code}")))
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR, f"{stock_code} 无复权因子数据",
            suggestion="请先同步复权因子数据"
        ))
    except Exception as e:
        logger.error(f"get_adj_factors failed: {e}")
        return format_tool_result(error_result(ErrorCodes.DATA_FETCH_ERROR, str(e)))


def get_trade_calendar(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """获取 A 股交易日历（开市/休市日期）。"""
    try:
        if not end_date:
            end_date = get_current_date_compact()
        if not start_date:
            start_date = (now_utc() - timedelta(days=90)).strftime('%Y%m%d')
        di = DataInterface.get_instance()
        result = run_async(di.read("CN", "trade_calendar",
                                   start_date=start_date, end_date=end_date))
        data = result.get("data")
        if data:
            import pandas as pd
            df = pd.DataFrame(data) if isinstance(data, list) else data
            return format_tool_result(success_result(format_result(df, "交易日历")))
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR, "无交易日历数据",
            suggestion="请先同步交易日历数据"
        ))
    except Exception as e:
        logger.error(f"get_trade_calendar failed: {e}")
        return format_tool_result(error_result(ErrorCodes.DATA_FETCH_ERROR, str(e)))


def get_index_basic() -> str:
    """获取指数基本信息（指数列表及元数据）。"""
    try:
        di = DataInterface.get_instance()
        result = run_async(di.read("CN", "index_basic"))
        data = result.get("data")
        if data:
            import pandas as pd
            df = pd.DataFrame(data) if isinstance(data, list) else data
            return format_tool_result(success_result(format_result(df, "指数基本信息")))
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR, "无指数基本信息数据",
            suggestion="请先同步指数基本信息数据"
        ))
    except Exception as e:
        logger.error(f"get_index_basic failed: {e}")
        return format_tool_result(error_result(ErrorCodes.DATA_FETCH_ERROR, str(e)))


def get_index_daily_basic(
    stock_code: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """获取指数每日指标（换手率、市盈率、市净率、市值等）。"""
    try:
        if not end_date:
            end_date = get_current_date_compact()
        if not start_date:
            start_date = (now_utc() - timedelta(days=90)).strftime('%Y%m%d')
        di = DataInterface.get_instance()
        clean_symbol = _normalize_symbol(stock_code, "CN")
        result = run_async(di.read("CN", "index_dailybasic", symbol=clean_symbol,
                                   start_date=start_date, end_date=end_date))
        data = result.get("data")
        if data:
            import pandas as pd
            df = pd.DataFrame(data) if isinstance(data, list) else data
            return format_tool_result(success_result(format_result(df, f"指数每日指标: {stock_code}")))
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR, f"无法获取 {stock_code} 指数每日指标",
            suggestion="请先同步指数每日指标数据"
        ))
    except Exception as e:
        logger.error(f"get_index_daily_basic failed: {e}")
        return format_tool_result(error_result(ErrorCodes.DATA_FETCH_ERROR, str(e)))


def get_index_global() -> str:
    """获取国际/海外指数行情（如美股三大指数、恒生、日经等）。"""
    try:
        di = DataInterface.get_instance()
        result = run_async(di.read("CN", "index_global"))
        data = result.get("data")
        if data:
            import pandas as pd
            df = pd.DataFrame(data) if isinstance(data, list) else data
            return format_tool_result(success_result(format_result(df, "国际指数")))
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR, "无国际指数数据",
            suggestion="请先同步国际指数数据"
        ))
    except Exception as e:
        logger.error(f"get_index_global failed: {e}")
        return format_tool_result(error_result(ErrorCodes.DATA_FETCH_ERROR, str(e)))


def get_index_weight(
    stock_code: str,
    trade_date: Optional[str] = None,
) -> str:
    """获取指数成分股及权重（分析指数贡献度、调仓影响）。"""
    try:
        if not trade_date:
            trade_date = get_current_date_compact()
        di = DataInterface.get_instance()
        clean_symbol = _normalize_symbol(stock_code, "CN")
        result = run_async(di.read("CN", "index_weight", symbol=clean_symbol,
                                   start_date=trade_date, end_date=trade_date))
        data = result.get("data")
        if data:
            import pandas as pd
            df = pd.DataFrame(data) if isinstance(data, list) else data
            return format_tool_result(success_result(format_result(df, f"指数成分权重: {stock_code}")))
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR, f"{stock_code} 无指数成分权重数据",
            suggestion="请先同步指数成分权重数据"
        ))
    except Exception as e:
        logger.error(f"get_index_weight failed: {e}")
        return format_tool_result(error_result(ErrorCodes.DATA_FETCH_ERROR, str(e)))
