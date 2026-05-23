"""
宏观经济工具 - 宏观经济数据
"""
import logging
from typing import Optional
from datetime import timedelta

from app.utils.time_utils import now_utc, get_current_date_compact
from app.engine.tools.common.tool_result import success_result, error_result, format_tool_result, ErrorCodes
from app.engine.tools.common.format import format_result
from app.data.core.interface import DataInterface
import asyncio
import pandas as pd

logger = logging.getLogger(__name__)


def get_macro_econ(
    indicator: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> str:
    """
    获取宏观经济数据。

    Args:
        indicator: 指标名称，支持 shibor、lpr、gdp、cpi、ppi、cn_m、cn_pmi、cn_sf 等
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
            result = asyncio.run(di.read("CN", "macro_economic", symbol=indicator,
                                         start_date=start_date, end_date=end_date))
            data = result.get("data")
            if data:
                df = pd.DataFrame(data) if isinstance(data, list) else data
                return format_tool_result(success_result(format_result(df, f"Macro: {indicator}")))
        except Exception:
            pass

        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            f"宏观经济数据暂不可用: {indicator}",
            suggestion="宏观数据功能待数据源对接后可用"
        ))
    except Exception as e:
        logger.error(f"get_macro_econ failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            str(e)
        ))


# --- 元数据 ---

TOOL_FUNCTIONS = [get_macro_econ]
DATA_SOURCE_MAP = {
    "get_macro_econ": ["tushare"],
}
ANALYST_MAP = {
    "get_macro_econ": ["china-market-analyst"],
}
