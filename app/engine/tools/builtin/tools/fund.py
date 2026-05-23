"""
基金工具 - 公募基金数据、基金经理查询
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


def get_fund_data(
    ts_code: str,
    data_type: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    period: Optional[str] = None
) -> str:
    """
    获取公募基金数据。

    Args:
        ts_code: 基金代码
        data_type: 数据类型，支持 basic、manager、nav、dividend、portfolio、all
        start_date: 开始日期，格式 YYYYMMDD，默认 3 个月前
        end_date: 结束日期，格式 YYYYMMDD，默认今天
        period: 报告期，可选

    Returns:
        JSON 格式的 ToolResult，包含 status、data、error_code、suggestion 字段
    """
    try:
        if not end_date:
            end_date = get_current_date_compact()
        if not start_date:
            start_date = (now_utc() - timedelta(days=90)).strftime('%Y%m%d')

        # 通过 DataInterface 尝试获取基金数据
        try:
            di = DataInterface.get_instance()
            result = asyncio.run(di.read("CN", "fund_data", symbol=ts_code,
                                         start_date=start_date, end_date=end_date))
            data = result.get("data")
            if data:
                df = pd.DataFrame(data) if isinstance(data, list) else data
                return format_tool_result(success_result(format_result(df, f"Fund: {ts_code} {data_type}")))
        except Exception:
            pass

        # AkShare 回退（仅支持 basic、nav、all 类型）
        if data_type in ["basic", "nav", "all"]:
            try:
                import akshare as ak

                logger.info(f"尝试使用AkShare获取基金数据: {ts_code}, 类型: {data_type}")
                df = ak.fund_open_fund_info_em(symbol=ts_code)

                if df is not None and not df.empty:
                    result_text = f"# {ts_code} 基金数据（来源：AkShare）\n\n"
                    result_text += f"**数据类型**: {data_type}\n\n"
                    result_text += "## 基金信息\n\n"
                    for col in df.columns:
                        value = df.iloc[0][col]
                        if pd.notna(value):
                            result_text += f"- **{col}**: {value}\n"
                    return result_text
            except Exception as ak_e:
                logger.warning(f"AkShare获取基金数据失败: {ak_e}")

        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            f"无法获取基金数据: {ts_code}, data_type: {data_type}",
            suggestion="请确认基金代码正确且数据源已配置"
        ))
    except Exception as e:
        logger.error(f"get_fund_data failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            str(e)
        ))


def get_fund_manager_by_name(
    name: str,
    ann_date: Optional[str] = None
) -> str:
    """
    根据姓名获取基金经理信息。

    Args:
        name: 基金经理姓名
        ann_date: 公告日期，格式 YYYYMMDD，可选

    Returns:
        JSON 格式的 ToolResult，包含 status、data、error_code、suggestion 字段
    """
    try:
        try:
            di = DataInterface.get_instance()
            result = asyncio.run(di.read("CN", "fund_managers", symbol=name))
            data = result.get("data")
            if data:
                df = pd.DataFrame(data) if isinstance(data, list) else data
                return format_tool_result(success_result(format_result(df, f"Manager: {name}")))
        except Exception:
            pass

        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            f"基金经理数据暂不可用: {name}",
            suggestion="基金经经理数据功能待数据源对接后可用"
        ))
    except Exception as e:
        logger.error(f"get_fund_manager_by_name failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            str(e)
        ))


# --- 元数据 ---

TOOL_FUNCTIONS = [get_fund_data, get_fund_manager_by_name]
DATA_SOURCE_MAP = {
    "get_fund_data": ["tushare", "akshare"],
    "get_fund_manager_by_name": ["tushare"],
}
ANALYST_MAP = {
    "get_fund_data": ["fundamentals-analyst"],
    "get_fund_manager_by_name": ["fundamentals-analyst"],
}
