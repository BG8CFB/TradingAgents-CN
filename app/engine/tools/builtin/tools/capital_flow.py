"""
资金流向工具 - 资金流向数据、融资融券数据
"""
import logging
from typing import Optional
from datetime import timedelta

from app.utils.time_utils import now_utc, get_current_date_compact
from app.engine.tools.builtin.standard import success_result, no_data_result, error_result, format_tool_result, ErrorCodes
from app.engine.tools.builtin.helpers import get_manager, format_result

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
        # 设置默认日期 (如果未提供 trade_date)
        if not trade_date:
            if not end_date:
                end_date = get_current_date_compact()
            if not start_date:
                start_date = (now_utc() - timedelta(days=30)).strftime('%Y%m%d')

        data = get_manager().get_money_flow(
            start_date=start_date,
            end_date=end_date,
            query_type=query_type,
            ts_code=ts_code,
            content_type=content_type,
            trade_date=trade_date
        )
        return format_tool_result(success_result(format_result(data, f"Money Flow: {ts_code or query_type}")))
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
        # 设置默认日期
        if not end_date:
            end_date = get_current_date_compact()
        if not start_date:
            start_date = (now_utc() - timedelta(days=30)).strftime('%Y%m%d')

        # 🔥 优先使用Tushare获取融资融券数据
        try:
            logger.info(f"📊 尝试使用Tushare获取融资融券数据: {data_type}")
            data = get_manager().get_margin_trade(
                data_type=data_type,
                start_date=start_date,
                end_date=end_date,
                ts_code=ts_code,
                exchange=exchange
            )
            if data and not data.empty:
                logger.info(f"✅ Tushare成功获取融资融券数据: {data_type}, {len(data)}条记录")
                return format_tool_result(success_result(format_result(data, f"Margin Trade: {data_type}")))
        except Exception as tu_e:
            logger.info(f"⚠️ Tushare获取融资融券数据失败: {tu_e}，尝试AkShare")

        # 回退到AkShare（暂不支持融资融券明细数据）
        # AkShare不提供个股融资融券明细接口，仅提供融资融券汇总数据
        logger.info(f"⚠️ AkShare暂不支持个股融资融券明细数据，仅Tushare支持")

        # 两个数据源都失败
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            f"无法从Tushare和AkShare获取融资融券数据: {data_type}"
        ))
    except Exception as e:
        logger.error(f"get_margin_trade failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            str(e)
        ))


# --- 元数据 ---

TOOL_FUNCTIONS = [get_money_flow, get_margin_trade]
DATA_SOURCE_MAP = {
    "get_money_flow": ["tushare"],
    "get_margin_trade": ["tushare"],
}
ANALYST_MAP = {
    "get_money_flow": ["short-term-capital-analyst", "china-market-analyst"],
    "get_margin_trade": ["short-term-capital-analyst"],
}
