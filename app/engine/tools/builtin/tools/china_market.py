"""
中国A股市场工具 - 市场概览、龙虎榜、大宗交易
"""
import json
import logging
import os
from typing import Optional
from datetime import datetime, timedelta

from app.utils.time_utils import now_utc, get_current_date, get_current_date_compact
from app.engine.tools.builtin.standard import success_result, no_data_result, error_result, format_tool_result, ErrorCodes
from app.engine.tools.builtin.helpers import get_manager, format_result

logger = logging.getLogger(__name__)


def get_china_market_overview(
    date: str = None,
    include_indices: bool = True,
    include_sectors: bool = True
) -> str:
    """
    获取中国A股市场整体概览。

    返回市场指数、板块表现、资金流向等宏观市场数据。

    Args:
        date: 查询日期，格式 YYYY-MM-DD，默认今天
        include_indices: 是否包含主要指数数据（上证、深证、创业板等）
        include_sectors: 是否包含板块表现数据

    Returns:
        JSON 格式的 ToolResult，包含 status、data、error_code、suggestion 字段
    """
    logger.info(f"🇨🇳 [MCP中国市场工具] 获取市场概览")
    start_time = now_utc()

    if not date:
        date = get_current_date()

    result_sections = []

    # 获取主要指数数据
    if include_indices:
        indices_data = []
        indices_source = "Unknown"

        # 定义关注的指数
        indices_to_fetch = [
            ('000001.SH', 'sh000001', '上证指数'),
            ('399001.SZ', 'sz399001', '深证成指'),
            ('399006.SZ', 'sz399006', '创业板指')
        ]

        # 1. 尝试使用 get_manager().get_index_data (支持 DB -> Tushare -> AKShare)
        try:
            for ts_code, ak_code, name in indices_to_fetch:
                # 优先尝试 Tushare 格式代码
                try:
                    # 使用 DataSourceManager 的逻辑
                    index_result = get_manager().get_index_data(code=ts_code, start_date=date, end_date=date)

                    # 简单解析返回的 Markdown 表格获取收盘价
                    if index_result and "|" in index_result:
                        lines = index_result.split('\n')
                        # 寻找包含日期的行
                        data_line = None
                        for line in lines:
                            if date.replace('-', '') in line or date in line:
                                data_line = line
                                break

                        if data_line:
                            indices_data.append(f"- **{name}**: (已获取，请查看详细指数数据)")
                            continue
                except Exception:
                    pass

                # 如果上面失败，尝试 AKShare 直接调用 (作为备用)
                try:
                    import akshare as ak
                    df = ak.stock_zh_index_daily(symbol=ak_code)
                    if not df.empty:
                        latest = df.iloc[-1]
                        close = latest.get('close', 'N/A')
                        indices_data.append(f"- **{name}**: {close}")
                        indices_source = "AKShare"
                except Exception as e:
                    logger.warning(f"获取 {name} 失败: {e}")

        except Exception as e:
            logger.warning(f"获取指数数据异常: {e}")

        if indices_data:
            result_sections.append(f"## 主要指数\n\n" + "\n".join(indices_data))
        else:
            result_sections.append("## 主要指数\n\n⚠️ 指数数据暂时无法获取")

    # 获取板块表现 (AKShare)
    if include_sectors:
        try:
            import akshare as ak
            import concurrent.futures

            # 使用线程池和超时机制执行 AKShare 调用，防止阻塞
            def fetch_sector_data():
                # 直接调用，异常由 future.result() 抛出并在主线程捕获
                return ak.stock_board_industry_name_em()

            sector_df = None
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(fetch_sector_data)
                    sector_df = future.result(timeout=15)  # 15秒超时
            except concurrent.futures.TimeoutError:
                logger.warning("AKShare 板块数据获取超时 (15s)")
                result_sections.append("## 板块表现\n\n⚠️ 数据获取超时，请稍后重试")
            except Exception as e:
                logger.warning(f"AKShare 板块数据获取异常: {e}")
                result_sections.append(f"## 板块表现\n\n⚠️ 数据源异常: {e}")

            if sector_df is not None and not sector_df.empty:
                # 取涨幅前5和跌幅前5
                top_sectors = sector_df.head(5)
                bottom_sectors = sector_df.tail(5)

                sector_info = "## 板块表现 (AKShare)\n\n"
                sector_info += "### 涨幅前5\n"
                for _, row in top_sectors.iterrows():
                    name = row.get('板块名称', 'N/A')
                    change = row.get('涨跌幅', 'N/A')
                    sector_info += f"- {name}: {change}%\n"

                sector_info += "\n### 跌幅前5\n"
                for _, row in bottom_sectors.iterrows():
                    name = row.get('板块名称', 'N/A')
                    change = row.get('涨跌幅', 'N/A')
                    sector_info += f"- {name}: {change}%\n"

                result_sections.append(sector_info)
            elif sector_df is None:
                # 错误信息已在上面添加
                pass
            else:
                result_sections.append("## 板块表现\n\n⚠️ 板块数据暂时无法获取 (空数据)")

        except Exception as e:
            logger.error(f"❌ [MCP中国市场工具] 获取板块数据失败: {e}")
            result_sections.append(f"## 板块表现\n\n⚠️ 获取失败: {e}")

    # 计算执行时间
    execution_time = (now_utc() - start_time).total_seconds()

    # 组合结果
    combined_result = f"""# 中国A股市场概览

**查询日期**: {date}
**执行时间**: {execution_time:.2f}秒

{chr(10).join(result_sections)}

---
*数据来源: AKShare/Tushare*
"""
    logger.info(f"🇨🇳 [MCP中国市场工具] 数据获取完成，总长度: {len(combined_result)}")
    return format_tool_result(success_result(combined_result))


def get_dragon_tiger_inst(
    trade_date: Optional[str] = None,
    ts_code: Optional[str] = None
) -> str:
    """
    获取龙虎榜机构明细。

    Args:
        trade_date: 交易日期，格式 YYYYMMDD，默认今天
        ts_code: 股票代码，可选

    Returns:
        JSON 格式的 ToolResult，包含 status、data、error_code、suggestion 字段
    """
    try:
        # 设置默认日期
        if not trade_date:
            trade_date = get_current_date_compact()

        # 🔥 优先使用Tushare获取龙虎榜数据（仅当配置了token时）
        tushare_token = os.getenv("TUSHARE_TOKEN")
        if tushare_token and tushare_token.strip():
            try:
                logger.info(f"📊 尝试使用Tushare获取龙虎榜数据: 日期{trade_date}")
                data = get_manager().get_dragon_tiger_inst(trade_date=trade_date, ts_code=ts_code)
                if data and not data.empty:
                    logger.info(f"✅ Tushare成功获取龙虎榜数据: {len(data)}条记录")
                    return format_tool_result(success_result(format_result(data, f"Dragon Tiger: {trade_date}")))
            except Exception as tu_e:
                logger.info(f"⚠️ Tushare获取龙虎榜数据失败: {tu_e}，尝试AkShare")
        else:
            logger.debug("⚠️ 未配置Tushare token，直接使用AkShare")

        # 回退到AkShare
        try:
            import akshare as ak
            import pandas as pd

            logger.info(f"📊 尝试使用AkShare获取龙虎榜数据: 日期{trade_date}")

            # 获取龙虎榜数据
            df = None
            try:
                # 方法1：使用东方财富龙虎榜接口（需要start_date和end_date）
                df = ak.stock_lhb_detail_em(start_date=trade_date, end_date=trade_date)
                # 检查是否返回None（API在某些日期可能没有数据）
                if df is None:
                    logger.warning(f"⚠️ stock_lhb_detail_em返回None（{trade_date}可能没有龙虎榜数据）")
                else:
                    logger.info(f"✅ 使用stock_lhb_detail_em成功获取数据: {len(df)}条记录")
            except Exception as em_e:
                logger.warning(f"⚠️ stock_lhb_detail_em失败: {em_e}，尝试其他接口")
                try:
                    # 方法2：尝试使用新浪龙虎榜接口
                    df = ak.stock_lhb_detail_daily_sina(date=trade_date)
                    logger.info(f"✅ 使用stock_lhb_detail_daily_sina成功获取数据")
                except Exception as sina_e:
                    logger.warning(f"⚠️ stock_lhb_detail_daily_sina也失败: {sina_e}")
                    df = None

            if df is not None and not df.empty:
                # 如果指定了股票代码，进行过滤
                if ts_code:
                    code_6digit = ts_code.replace('.SH', '').replace('.SZ', '').replace('.sh', '').replace('.sz', '').zfill(6)
                    # 尝试多种可能的列名
                    df_filtered = None
                    for col_name in ['代码', '股票代码', 'symbol', 'stock_code']:
                        if col_name in df.columns:
                            df_filtered = df[df[col_name] == code_6digit]
                            if not df_filtered.empty:
                                break

                    if df_filtered is None or df_filtered.empty:
                        logger.info(f"⚠️ AkShare未找到{ts_code}的龙虎榜数据，返回全部数据")
                        df_filtered = df
                    else:
                        logger.info(f"✅ AkShare找到{ts_code}的龙虎榜数据: {len(df_filtered)}条记录")
                else:
                    df_filtered = df

                logger.info(f"✅ AkShare成功获取龙虎榜数据: {len(df_filtered)}条记录")

                # 返回JSON格式
                data_dict = df_filtered.head(50).to_dict(orient='records')
                json_data = json.dumps(data_dict, ensure_ascii=False, default=str)
                return format_tool_result(success_result(
                    data=json_data,
                ))
            else:
                logger.warning(f"⚠️ AkShare龙虎榜接口返回空数据")
        except Exception as ak_e:
            logger.warning(f"⚠️ AkShare获取龙虎榜数据失败: {ak_e}")

        # 两个数据源都失败
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            f"无法从Tushare和AkShare获取龙虎榜数据: {trade_date}"
        ))
    except Exception as e:
        logger.error(f"get_dragon_tiger_inst failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            str(e)
        ))


def get_block_trade(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    code: Optional[str] = None
) -> str:
    """
    获取大宗交易数据。

    Args:
        start_date: 开始日期，格式 YYYYMMDD，默认 7 天前
        end_date: 结束日期，格式 YYYYMMDD，默认今天
        code: 股票代码，可选

    Returns:
        JSON 格式的 ToolResult，包含 status、data、error_code、suggestion 字段
    """
    try:
        # 设置默认日期
        if not end_date:
            end_date = get_current_date_compact()
        if not start_date:
            start_date = (now_utc() - timedelta(days=7)).strftime('%Y%m%d')

        # 🔥 优先使用Tushare获取大宗交易数据（仅当配置了token时）
        tushare_token = os.getenv("TUSHARE_TOKEN")
        if tushare_token and tushare_token.strip():
            try:
                logger.info(f"📊 尝试使用Tushare获取大宗交易数据")
                data = get_manager().get_block_trade(start_date=start_date, end_date=end_date, code=code)
                if data and not data.empty:
                    logger.info(f"✅ Tushare成功获取大宗交易数据: {len(data)}条记录")
                    return format_tool_result(success_result(format_result(data, f"Block Trade: {code or 'All'}")))
            except Exception as tu_e:
                logger.info(f"⚠️ Tushare获取大宗交易数据失败: {tu_e}，尝试AkShare")
        else:
            logger.debug("⚠️ 未配置Tushare token，直接使用AkShare")

        # 回退到AkShare
        try:
            import akshare as ak
            import pandas as pd

            logger.info(f"📊 尝试使用AkShare获取大宗交易数据: 日期范围{start_date}-{end_date}")

            # 使用正确的AkShare大宗交易接口：stock_dzjy_mrmx（每日明细）
            df = ak.stock_dzjy_mrmx(symbol='A股', start_date=start_date, end_date=end_date)

            if df is not None and not df.empty:
                logger.info(f"✅ AkShare成功获取大宗交易数据: {len(df)}条记录")

                # 如果指定了股票代码，进行过滤
                if code:
                    code_6digit = code.replace('.SH', '').replace('.SZ', '').replace('.sh', '').replace('.sz', '').zfill(6)
                    # 尝试多种可能的列名（根据实际测试）
                    for col_name in ['证券代码', '代码', 'symbol', 'stock_code']:
                        if col_name in df.columns:
                            df_filtered = df[df[col_name] == code_6digit]
                            if not df_filtered.empty:
                                break
                    else:
                        df_filtered = df

                    if df_filtered.empty:
                        logger.info(f"⚠️ AkShare未找到{code}的大宗交易数据，返回全部数据")
                        df_filtered = df
                    else:
                        logger.info(f"✅ AkShare找到{code}的大宗交易数据: {len(df_filtered)}条记录")
                else:
                    df_filtered = df

                # 返回JSON格式
                data_dict = df_filtered.head(50).to_dict(orient='records')
                json_data = json.dumps(data_dict, ensure_ascii=False, default=str)
                return format_tool_result(success_result(
                    data=json_data,
                ))
            else:
                logger.warning(f"⚠️ AkShare大宗交易接口返回空数据")
        except Exception as ak_e:
            logger.warning(f"⚠️ AkShare获取大宗交易数据失败: {ak_e}")

        # 两个数据源都失败
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            f"无法从Tushare和AkShare获取大宗交易数据"
        ))
    except Exception as e:
        logger.error(f"get_block_trade failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            str(e)
        ))


# --- 元数据 ---

TOOL_FUNCTIONS = [get_china_market_overview, get_dragon_tiger_inst, get_block_trade]
DATA_SOURCE_MAP = {
    "get_china_market_overview": ["tushare", "akshare"],
    "get_dragon_tiger_inst": ["tushare", "akshare"],
    "get_block_trade": ["tushare", "akshare"],
}
ANALYST_MAP = {
    "get_china_market_overview": ["china-market-analyst", "short-term-capital-analyst"],
    "get_dragon_tiger_inst": ["china-market-analyst", "short-term-capital-analyst"],
    "get_block_trade": ["china-market-analyst", "short-term-capital-analyst"],
}
