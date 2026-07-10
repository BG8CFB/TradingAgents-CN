"""
板块/行业工具 - 申万行业指数、同花顺板块、板块资金流
"""
import json
import logging
from typing import Optional
from datetime import timedelta

from app.utils.time_utils import now_utc, get_current_date, get_current_date_compact
from app.engine.tools.common.tool_result import success_result, error_result, format_tool_result, ErrorCodes
from app.engine.tools.common.format import format_result
from app.data.core.interface import DataInterface
from app.core.async_utils import run_async

logger = logging.getLogger(__name__)


def _tushare_fallback(api_name, query_kwargs, display_name):
    """通用 tushare 直接回退"""
    try:
        from app.data.sources.cn.tushare.api.connection import get_tushare_api
        conn = get_tushare_api()
        if not conn.is_available():
            return None
        import asyncio
        df = asyncio.run(asyncio.to_thread(getattr(conn.api, api_name), **query_kwargs))
        if df is not None and not df.empty:
            return format_tool_result(success_result(format_result(df, f"{display_name} (tushare实时)")))
    except Exception as e:
        logger.debug(f"tushare {api_name} 回退失败: {e}")
    return None


def get_sw_daily(
    ts_code: Optional[str] = None,
    trade_date: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """获取申万行业指数日行情（板块强弱分析）。"""
    try:
        if not trade_date and not start_date:
            trade_date = get_current_date_compact()
        trade_date = str(trade_date).replace("-", "") if trade_date else None
        if start_date:
            start_date = str(start_date).replace("-", "")
        if end_date:
            end_date = str(end_date).replace("-", "")

        # 先尝试 MongoDB
        try:
            di = DataInterface.get_instance()
            result = run_async(di.read("CN", "sw_daily",
                                        start_date=start_date or trade_date,
                                        end_date=end_date or trade_date))
            data = result.get("data")
            if data:
                import pandas as pd
                df = pd.DataFrame(data) if isinstance(data, list) else data
                if ts_code and "ts_code" in df.columns:
                    df = df[df["ts_code"] == ts_code]
                return format_tool_result(success_result(format_result(df, "申万行业指数")))
        except Exception:
            pass

        # 回退到 tushare 直接获取
        kwargs = {}
        if ts_code:
            kwargs["ts_code"] = ts_code
        if trade_date:
            kwargs["trade_date"] = trade_date
        elif start_date:
            kwargs["start_date"] = start_date
            kwargs["end_date"] = end_date or start_date
        fallback = _tushare_fallback("sw_daily", kwargs, "申万行业指数")
        if fallback:
            return fallback

        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            "申万行业指数数据暂不可用",
            suggestion="请先同步 sw_daily 数据"
        ))
    except Exception as e:
        logger.error(f"get_sw_daily failed: {e}")
        return format_tool_result(error_result(ErrorCodes.DATA_FETCH_ERROR, str(e)))


def get_ths_daily(
    ts_code: Optional[str] = None,
    trade_date: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """获取同花顺概念/行业板块行情。"""
    try:
        if not trade_date and not start_date:
            trade_date = get_current_date_compact()
        trade_date = str(trade_date).replace("-", "") if trade_date else None
        if start_date:
            start_date = str(start_date).replace("-", "")
        if end_date:
            end_date = str(end_date).replace("-", "")

        try:
            di = DataInterface.get_instance()
            result = run_async(di.read("CN", "ths_daily",
                                        start_date=start_date or trade_date,
                                        end_date=end_date or trade_date))
            data = result.get("data")
            if data:
                import pandas as pd
                df = pd.DataFrame(data) if isinstance(data, list) else data
                if ts_code and "ts_code" in df.columns:
                    df = df[df["ts_code"] == ts_code]
                return format_tool_result(success_result(format_result(df, "同花顺板块行情")))
        except Exception:
            pass

        kwargs = {}
        if ts_code:
            kwargs["ts_code"] = ts_code
        if trade_date:
            kwargs["trade_date"] = trade_date
        elif start_date:
            kwargs["start_date"] = start_date
            kwargs["end_date"] = end_date or start_date
        fallback = _tushare_fallback("ths_daily", kwargs, "同花顺板块行情")
        if fallback:
            return fallback

        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            "同花顺板块行情数据暂不可用",
            suggestion="请先同步 ths_daily 数据"
        ))
    except Exception as e:
        logger.error(f"get_ths_daily failed: {e}")
        return format_tool_result(error_result(ErrorCodes.DATA_FETCH_ERROR, str(e)))


def get_moneyflow_ind_dc(
    trade_date: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """获取东方财富板块资金流向。"""
    try:
        if not trade_date and not start_date:
            trade_date = get_current_date_compact()
        trade_date = str(trade_date).replace("-", "") if trade_date else None
        if start_date:
            start_date = str(start_date).replace("-", "")
        if end_date:
            end_date = str(end_date).replace("-", "")

        try:
            di = DataInterface.get_instance()
            result = run_async(di.read("CN", "moneyflow_ind_dc",
                                        start_date=start_date or trade_date,
                                        end_date=end_date or trade_date))
            data = result.get("data")
            if data:
                import pandas as pd
                df = pd.DataFrame(data) if isinstance(data, list) else data
                return format_tool_result(success_result(format_result(df, "板块资金流向")))
        except Exception:
            pass

        kwargs = {}
        if trade_date:
            kwargs["trade_date"] = trade_date
        elif start_date:
            kwargs["start_date"] = start_date
            kwargs["end_date"] = end_date or start_date
        fallback = _tushare_fallback("moneyflow_ind_dc", kwargs, "板块资金流向")
        if fallback:
            return fallback

        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            "板块资金流向数据暂不可用",
            suggestion="请先同步 moneyflow_ind_dc 数据"
        ))
    except Exception as e:
        logger.error(f"get_moneyflow_ind_dc failed: {e}")
        return format_tool_result(error_result(ErrorCodes.DATA_FETCH_ERROR, str(e)))
