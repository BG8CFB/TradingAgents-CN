"""
资金流向工具 - 资金流向数据、融资融券数据
"""
import logging
from typing import Optional
from datetime import timedelta

from app.utils.time_utils import now_utc, get_current_date_compact
from app.engine.tools.common.tool_result import success_result, error_result, format_tool_result, ErrorCodes
from app.engine.tools.common.format import format_result
from app.data.core.interface import DataInterface
from app.core.async_utils import run_async
import pandas as pd

logger = logging.getLogger(__name__)


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
        if not trade_date:
            if not end_date:
                end_date = get_current_date_compact()
            if not start_date:
                start_date = (now_utc() - timedelta(days=30)).strftime('%Y%m%d')

        symbol = ts_code or "market"
        try:
            di = DataInterface.get_instance()
            result = run_async(di.read("CN", "money_flow", symbol=symbol,
                                         start_date=start_date, end_date=end_date))
            data = result.get("data")
            if data:
                df = pd.DataFrame(data) if isinstance(data, list) else data
                return format_tool_result(success_result(format_result(df, f"Money Flow: {ts_code or query_type}")))
        except Exception:
            pass

        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            f"资金流向数据暂不可用: {ts_code or query_type}",
            suggestion="请先通过同步任务获取资金流向数据，或确认数据源已配置"
        ))
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
        if not end_date:
            end_date = get_current_date_compact()
        if not start_date:
            start_date = (now_utc() - timedelta(days=30)).strftime('%Y%m%d')

        symbol = ts_code or "market"
        try:
            di = DataInterface.get_instance()
            result = run_async(di.read("CN", "margin_trading", symbol=symbol,
                                         start_date=start_date, end_date=end_date))
            data = result.get("data")
            if data:
                df = pd.DataFrame(data) if isinstance(data, list) else data
                return format_tool_result(success_result(format_result(df, f"Margin Trade: {data_type}")))
        except Exception:
            pass

        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            f"融资融券数据暂不可用: {data_type}",
            suggestion="请先通过同步任务获取融资融券数据，或确认数据源已配置"
        ))
    except Exception as e:
        logger.error(f"get_margin_trade failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            str(e)
        ))
