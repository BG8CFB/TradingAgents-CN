"""
基金工具 - 公募基金数据、基金经理查询
"""
import logging
from typing import Optional
from datetime import timedelta

from app.utils.time_utils import now_utc, get_current_date_compact
from app.engine.tools.builtin.standard import success_result, no_data_result, error_result, format_tool_result, ErrorCodes
from app.engine.tools.builtin.helpers import get_manager, format_result

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
        # 设置默认日期
        if not end_date:
            end_date = get_current_date_compact()
        if not start_date:
            start_date = (now_utc() - timedelta(days=90)).strftime('%Y%m%d')

        # 🔥 优先使用Tushare获取基金数据
        try:
            logger.info(f"📊 尝试使用Tushare获取基金数据: {ts_code}, 类型: {data_type}")
            data = get_manager().get_fund_data(
                ts_code=ts_code,
                data_type=data_type,
                start_date=start_date,
                end_date=end_date,
                period=period
            )
            if data and not data.empty:
                logger.info(f"✅ Tushare成功获取基金数据: {ts_code}, {len(data)}条记录")
                return format_tool_result(success_result(format_result(data, f"Fund: {ts_code} {data_type}")))
        except Exception as tu_e:
            logger.info(f"⚠️ Tushare获取基金数据失败: {tu_e}，尝试AkShare")

        # 回退到AkShare（仅支持basic、nav、all类型）
        if data_type in ["basic", "nav", "all"]:
            try:
                import akshare as ak
                import pandas as pd

                logger.info(f"📊 尝试使用AkShare获取基金数据: {ts_code}, 类型: {data_type}")

                # 获取基金信息（注意：fund_open_fund_info_em不需要year参数）
                df = ak.fund_open_fund_info_em(symbol=ts_code)

                if df is not None and not df.empty:
                    logger.info(f"✅ AkShare成功获取基金数据: {ts_code}")

                    # 格式化数据
                    result_text = f"# {ts_code} 基金数据（来源：AkShare）\n\n"
                    result_text += f"**数据类型**: {data_type}\n\n"

                    result_text += "## 基金信息\n\n"
                    for col in df.columns:
                        value = df.iloc[0][col]
                        # 处理NaN值
                        if pd.notna(value):
                            result_text += f"- **{col}**: {value}\n"

                    return result_text
                else:
                    logger.warning(f"⚠️ AkShare未获取到基金数据")
            except Exception as ak_e:
                logger.warning(f"⚠️ AkShare获取基金数据失败: {ak_e}")

        # 两个数据源都失败
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            f"无法从Tushare和AkShare获取基金数据: {ts_code}, data_type: {data_type}"
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
        data = get_manager().get_fund_manager_by_name(name=name, ann_date=ann_date)
        return format_tool_result(success_result(format_result(data, f"Manager: {name}")))
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
