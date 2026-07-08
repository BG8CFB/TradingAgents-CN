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
        if ts_code:
            symbol = ts_code.replace('.SZ', '').replace('.SH', '').replace('.BJ', '') \
                             .replace('.sz', '').replace('.sh', '').replace('.bj', '').zfill(6)
        try:
            di = DataInterface.get_instance()
            result = run_async(di.read("CN", "money_flow", symbol=symbol,
                                         start_date=start_date, end_date=end_date))
            data = result.get("data")
            if data:
                df = pd.DataFrame(data) if isinstance(data, list) else data
                return format_tool_result(success_result(format_result(df, f"Money Flow: {ts_code or query_type}")))
        except Exception as e:
            logger.debug(f"资金流向数据获取失败: {e}")
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
        if ts_code:
            symbol = ts_code.replace('.SZ', '').replace('.SH', '').replace('.BJ', '') \
                             .replace('.sz', '').replace('.sh', '').replace('.bj', '').zfill(6)
        try:
            di = DataInterface.get_instance()
            result = run_async(di.read("CN", "margin_trading", symbol=symbol,
                                         start_date=start_date, end_date=end_date))
            data = result.get("data")
            if data:
                df = pd.DataFrame(data) if isinstance(data, list) else data
                return format_tool_result(success_result(format_result(df, f"Margin Trade: {data_type}")))
        except Exception as e:
            logger.debug(f"融资融券数据获取失败: {e}")
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


def get_northbound_flow(
    trade_date: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """获取北向资金流向数据。"""
    try:
        if not end_date:
            end_date = get_current_date_compact()
        if not start_date:
            start_date = (now_utc() - timedelta(days=30)).strftime('%Y%m%d')
        
        # 尝试直接获取数据
        try:
            di = DataInterface.get_instance()
            result = run_async(di.read("CN", "northbound_flow", symbol="__all__",
                                         start_date=start_date, end_date=end_date))
            data = result.get("data")
            if data:
                df = pd.DataFrame(data) if isinstance(data, list) else data
                return format_tool_result(success_result(format_result(df, "北向资金流向")))
        except Exception as e:
            # 如果 run_async 失败，尝试使用 Tushare 直接获取
            logger.debug(f"DataInterface 获取失败: {e}，尝试使用 Tushare 直接获取")
            from app.data.sources.cn.tushare.api.connection import get_tushare_api
            from app.data.sources.cn.tushare.api.northbound_flow import fetch_northbound_flow
            
            conn = get_tushare_api()
            if conn.is_available():
                df = run_async(fetch_northbound_flow(conn, start_date=start_date, end_date=end_date))
                if df is not None and not df.empty:
                    return format_tool_result(success_result(format_result(df, "北向资金流向")))
        
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR, "北向资金数据暂不可用",
            suggestion="请先同步北向资金数据"
        ))
    except Exception as e:
        logger.error(f"get_northbound_flow failed: {e}")
        return format_tool_result(error_result(ErrorCodes.DATA_FETCH_ERROR, str(e)))


def get_northbound_holding(
    ts_code: Optional[str] = None,
    trade_date: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """获取北向资金数据（沪深股通十大成交股）。

    注：tushare 没有单只 A 股的北向持仓明细接口。
    hk_hold 返回的是港股数据（南向），不是 A 股北向持仓。
    此接口改用 hsgt_top10 返回北向资金活跃个股名单。
    """
    try:
        if not trade_date:
            if end_date:
                trade_date = end_date
            else:
                trade_date = get_current_date_compact()
        trade_date = str(trade_date).replace("-", "")

        from app.data.sources.cn.tushare.api.connection import get_tushare_api
        from app.data.sources.cn.tushare.api.northbound_holding import fetch_northbound_holding

        conn = get_tushare_api()
        if not conn.is_available():
            return format_tool_result(error_result(
                ErrorCodes.DATA_FETCH_ERROR,
                "Tushare 连接不可用",
                suggestion="请检查 TUSHARE_TOKEN 配置"
            ))

        # 尝试获取数据
        try:
            result = run_async(fetch_northbound_holding(
                conn, ts_code=ts_code, trade_date=trade_date
            ))
        except RuntimeError as e:
            # 如果 run_async 失败（可能在事件循环中），尝试直接获取
            if "run_async() 不能在主线程的事件循环中调用" in str(e) or "cannot be called from a running event loop" in str(e):
                logger.debug("run_async 失败，尝试直接获取")
                import asyncio
                result = asyncio.run(fetch_northbound_holding(
                    conn, ts_code=ts_code, trade_date=trade_date
                ))
            else:
                raise

        if result is None or result.empty:
            if ts_code:
                # 股票不在 top10 名单中，先获取全量 top10 再说明
                try:
                    all_top10 = run_async(fetch_northbound_holding(conn, trade_date=trade_date))
                except RuntimeError as e:
                    if "run_async() 不能在主线程的事件循环中调用" in str(e) or "cannot be called from a running event loop" in str(e):
                        import asyncio
                        all_top10 = asyncio.run(fetch_northbound_holding(conn, trade_date=trade_date))
                    else:
                        raise
                top10_str = ""
                if all_top10 is not None and not all_top10.empty:
                    top10_str = f"\n\n当日十大成交股：\n" + format_result(all_top10, "北向资金十大成交股")
                return format_tool_result(success_result(
                    f"## 北向资金数据\n\n"
                    f"**{ts_code}** 不在日期 {trade_date} 沪深股通十大成交股名单中。\n\n"
                    f"说明：tushare 不提供单只 A 股的北向持仓明细，仅提供每日十大活跃股。"
                    f"如需整体北向资金流向，请使用 moneyflow_hsgt 接口。"
                    f"{top10_str}"
                ))
            return format_tool_result(error_result(
                ErrorCodes.DATA_FETCH_ERROR,
                f"日期 {trade_date} 无北向资金数据（可能为非交易日）",
                suggestion="请确认日期是否为交易日"
            ))

        return format_tool_result(success_result(
            format_result(result, f"北向资金十大成交股 ({trade_date})")
        ))
    except Exception as e:
        logger.error(f"get_northbound_holding failed: {e}")
        return format_tool_result(error_result(ErrorCodes.DATA_FETCH_ERROR, str(e)))
