"""
连板天梯工具 - 涨停连板数据
"""
import json
import logging
from typing import Optional

from app.utils.time_utils import now_utc, get_current_date, get_current_date_compact
from app.engine.tools.common.tool_result import success_result, error_result, format_tool_result, ErrorCodes
from app.engine.tools.common.format import format_result
from app.data.core.interface import DataInterface
from app.core.async_utils import run_async

logger = logging.getLogger(__name__)


def get_limit_step(
    ts_code: Optional[str] = None,
    trade_date: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """获取连板天梯数据（涨停连板梯队）。"""
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
            result = run_async(di.read("CN", "limit_step",
                                        start_date=start_date or trade_date,
                                        end_date=end_date or trade_date))
            data = result.get("data")
            if data:
                import pandas as pd
                df = pd.DataFrame(data) if isinstance(data, list) else data
                if ts_code and "ts_code" in df.columns:
                    df = df[df["ts_code"] == ts_code]
                return format_tool_result(success_result(format_result(df, "连板天梯")))
        except Exception:
            pass

        # 回退到 tushare 直接获取
        try:
            from app.data.sources.cn.tushare.api.connection import get_tushare_api
            import asyncio
            conn = get_tushare_api()
            if conn.is_available():
                kwargs = {}
                if ts_code:
                    kwargs["ts_code"] = ts_code
                if trade_date:
                    kwargs["trade_date"] = trade_date
                elif start_date:
                    kwargs["start_date"] = start_date
                    kwargs["end_date"] = end_date or start_date
                df = asyncio.run(asyncio.to_thread(conn.api.limit_step, **kwargs))
                if df is not None and not df.empty:
                    return format_tool_result(success_result(format_result(df, "连板天梯 (tushare实时)")))
        except Exception as e:
            logger.debug(f"tushare limit_step 回退失败: {e}")

        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            "连板天梯数据暂不可用",
            suggestion="请先同步 limit_step 数据"
        ))
    except Exception as e:
        logger.error(f"get_limit_step failed: {e}")
        return format_tool_result(error_result(ErrorCodes.DATA_FETCH_ERROR, str(e)))
