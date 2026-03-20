"""
宏观经济工具 - 宏观经济数据
"""
import logging
from typing import Optional
from datetime import timedelta

from app.utils.time_utils import now_utc, get_current_date_compact
from app.engine.tools.builtin.standard import success_result, no_data_result, error_result, format_tool_result, ErrorCodes
from app.engine.tools.builtin.helpers import get_manager, format_result

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
        # 设置默认日期
        if not end_date:
            end_date = get_current_date_compact()
        if not start_date:
            start_date = (now_utc() - timedelta(days=90)).strftime('%Y%m%d')

        data = get_manager().get_macro_econ(indicator=indicator, start_date=start_date, end_date=end_date)
        return format_tool_result(success_result(format_result(data, f"Macro: {indicator}")))
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
