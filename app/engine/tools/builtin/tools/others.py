"""
其他工具 - 可转债数据、中证指数成份股
"""
import json
import logging
from typing import Optional
from datetime import timedelta

from app.utils.time_utils import now_utc, get_current_date_compact
from app.engine.tools.builtin.standard import success_result, no_data_result, error_result, format_tool_result, ErrorCodes
from app.engine.tools.builtin.helpers import get_manager, format_result

logger = logging.getLogger(__name__)


def get_convertible_bond(
    data_type: str,
    ts_code: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> str:
    """
    获取可转债数据。

    Args:
        data_type: 数据类型，支持 issue(发行信息)、info(基本信息)
        ts_code: 转债代码
        start_date: 开始日期，格式 YYYYMMDD
        end_date: 结束日期，格式 YYYYMMDD

    Returns:
        JSON 格式的 ToolResult，包含 status、data、error_code、suggestion 字段
    """
    try:
        import os

        # 🔥 优先使用Tushare获取可转债数据（仅当配置了token时）
        tushare_token = os.getenv("TUSHARE_TOKEN")
        if tushare_token and tushare_token.strip():
            try:
                logger.info(f"📊 尝试使用Tushare获取可转债数据: 类型{data_type}")
                data = get_manager().get_convertible_bond(
                    data_type=data_type,
                    ts_code=ts_code,
                    start_date=start_date,
                    end_date=end_date
                )
                if data and not data.empty:
                    logger.info(f"✅ Tushare成功获取可转债数据: {len(data)}条记录")
                    return format_tool_result(success_result(format_result(data, f"CB: {data_type}")))
            except Exception as tu_e:
                logger.info(f"⚠️ Tushare获取可转债数据失败: {tu_e}，尝试AkShare")
        else:
            logger.debug("⚠️ 未配置Tushare token，直接使用AkShare")

        # 回退到AkShare
        try:
            import akshare as ak
            import pandas as pd

            logger.info(f"📊 尝试使用AkShare获取可转债数据: 类型{data_type}")

            # 获取可转债数据
            df = ak.bond_cb_jsl()

            if df is not None and not df.empty:
                logger.info(f"✅ AkShare成功获取可转债数据: {len(df)}条记录")

                # 如果指定了转债代码，进行过滤（尝试所有可能的列名）
                if ts_code:
                    df_filtered = None
                    # 尝试直接在所有列中查找匹配的值
                    for col in df.columns:
                        if df[col].dtype == 'object':
                            matched = df[df[col].astype(str).str.contains(ts_code, na=False)]
                            if not matched.empty:
                                df_filtered = matched
                                logger.info(f"✅ 在列'{col}'中找到{ts_code}的可转债数据")
                                break

                    if df_filtered is None or df_filtered.empty:
                        logger.info(f"⚠️ AkShare未找到{ts_code}的可转债数据，返回全部数据")
                        df_filtered = df
                    else:
                        logger.info(f"✅ AkShare找到{ts_code}的可转债数据: {len(df_filtered)}条记录")
                else:
                    df_filtered = df

                # 按日期范围过滤（如果提供了日期）
                if start_date or end_date:
                    # 尝试找到日期列并过滤
                    date_col = None
                    for col in df_filtered.columns:
                        # 检查第一行数据是否为datetime类型
                        if len(df_filtered) > 0:
                            sample_val = df_filtered[col].iloc[0]
                            # 使用pd.Timestamp而不是datetime来避免变量冲突
                            if isinstance(sample_val, pd.Timestamp):
                                date_col = col
                                break

                    if date_col:
                        if start_date:
                            # 使用pd.to_datetime解析日期字符串，避免datetime变量冲突
                            start_dt = pd.to_datetime(start_date)
                            df_filtered = df_filtered[df_filtered[date_col] >= start_dt]

                        if end_date:
                            end_dt = pd.to_datetime(end_date)
                            df_filtered = df_filtered[df_filtered[date_col] <= end_dt]

                        logger.info(f"✅ 按日期范围过滤后剩余: {len(df_filtered)}条记录")

                # 返回JSON格式
                data_dict = df_filtered.head(50).to_dict(orient='records')
                json_data = json.dumps(data_dict, ensure_ascii=False, default=str)
                return format_tool_result(success_result(
                    data=json_data,
                ))
            else:
                logger.warning(f"⚠️ AkShare可转债接口返回空数据")
        except Exception as ak_e:
            logger.warning(f"⚠️ AkShare获取可转债数据失败: {ak_e}")

        # 两个数据源都失败
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            f"无法从Tushare和AkShare获取可转债数据: {data_type}"
        ))
    except Exception as e:
        logger.error(f"get_convertible_bond failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            str(e)
        ))


def get_csi_index_constituents(
    index_code: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> str:
    """
    获取中证指数成份股及权重。

    Args:
        index_code: 指数代码
        start_date: 开始日期，格式 YYYYMMDD，默认 1 个月前
        end_date: 结束日期，格式 YYYYMMDD，默认今天

    Returns:
        JSON 格式的 ToolResult，包含 status、data、error_code、suggestion 字段
    """
    try:
        # 设置默认日期
        if not end_date:
            end_date = get_current_date_compact()
        if not start_date:
            start_date = (now_utc() - timedelta(days=30)).strftime('%Y%m%d')

        data = get_manager().get_csi_index_constituents(index_code=index_code, start_date=start_date, end_date=end_date)
        return format_tool_result(success_result(format_result(data, f"CSI Constituents: {index_code}")))
    except Exception as e:
        logger.error(f"get_csi_index_constituents failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            str(e)
        ))


# --- 元数据 ---

TOOL_FUNCTIONS = [get_convertible_bond, get_csi_index_constituents]
DATA_SOURCE_MAP = {
    "get_convertible_bond": ["tushare", "akshare"],
    "get_csi_index_constituents": ["tushare"],
}
ANALYST_MAP = {
    "get_convertible_bond": ["fundamentals-analyst"],
    "get_csi_index_constituents": ["fundamentals-analyst"],
}
