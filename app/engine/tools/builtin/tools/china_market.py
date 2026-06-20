"""
中国A股市场工具 - 市场概览、龙虎榜、大宗交易

主要数据通过 DataInterface 统一获取，走 FallbackRouter 自动降级。
板块行情属于高频实时快照，通过东方财富 API 直接获取（不经过 DataInterface）。
"""
import json
import logging
from typing import Optional
from datetime import timedelta

from app.utils.time_utils import now_utc, get_current_date, get_current_date_compact
from app.engine.tools.common.tool_result import success_result, error_result, format_tool_result, ErrorCodes
from app.data.core.interface import DataInterface
from app.core.async_utils import run_async
logger = logging.getLogger(__name__)


def get_china_market_overview(
    date: str = None,
    include_indices: bool = True,
    include_sectors: bool = True
) -> str:
    """
    获取中国A股市场整体概览。

    返回市场指数、板块表现等宏观市场数据。

    Args:
        date: 查询日期，格式 YYYY-MM-DD，默认今天
        include_indices: 是否包含主要指数数据（上证、深证、创业板等）
        include_sectors: 是否包含板块表现数据

    Returns:
        JSON 格式的 ToolResult
    """
    logger.info("[中国市场工具] 获取市场概览")
    start_time = now_utc()

    if not date:
        date = get_current_date()

    result_sections = []

    if include_indices:
        indices_to_fetch = [
            ('000001', '上证指数'),
            ('399001', '深证成指'),
            ('399006', '创业板指'),
        ]

        indices_data = []
        try:
            di = DataInterface.get_instance()
            for symbol, name in indices_to_fetch:
                try:
                    result = run_async(di.read("CN", "market_quotes", symbol=symbol))
                    data = result.get("data")
                    if data:
                        if isinstance(data, dict):
                            price = data.get("last_price", "N/A")
                        elif isinstance(data, list) and data:
                            price = data[0].get("last_price", "N/A")
                        else:
                            price = "N/A"
                        indices_data.append(f"- **{name}**: {price}")
                except Exception as e:
                    logger.warning(f"获取 {name} 失败: {e}")
        except Exception as e:
            logger.warning(f"获取指数数据异常: {e}")

        if indices_data:
            result_sections.append("## 主要指数\n\n" + "\n".join(indices_data))
        else:
            result_sections.append("## 主要指数\n\n指数数据暂时无法获取（请先同步 market_quotes 数据）")

    if include_sectors:
        try:

            sector_df = None

            # 板块行情是高频实时快照数据，无法通过"同步→缓存→读取"模式管理
            # 因此直接调用东方财富 API 获取，不经过 DataInterface
            try:
                from app.utils.anti_scraping import fetch_em_board_direct
                board_data = fetch_em_board_direct()
                if board_data:
                    import pandas as pd
                    sector_df = pd.DataFrame(board_data)
                    sector_df = sector_df.rename(columns={"f14": "板块名称", "f3": "涨跌幅", "f2": "最新价"})
                    sector_df = sector_df.sort_values("涨跌幅", ascending=False)
                    logger.info(f"东方财富 API 板块数据获取成功: {len(sector_df)} 条")
            except Exception as e:
                logger.warning(f"东方财富 API 板块数据失败: {e}")

            if sector_df is not None and not sector_df.empty:
                top_sectors = sector_df.head(5)
                bottom_sectors = sector_df.tail(5)

                sector_info = "## 板块表现\n\n"
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
            elif not result_sections:
                result_sections.append("## 板块表现\n\n板块数据暂时无法获取 (空数据)")

        except Exception as e:
            logger.error(f"[中国市场工具] 获取板块数据失败: {e}")
            result_sections.append(f"## 板块表现\n\n获取失败: {e}")

    execution_time = (now_utc() - start_time).total_seconds()

    combined_result = f"""# 中国A股市场概览

**查询日期**: {date}
**执行时间**: {execution_time:.2f}秒

{chr(10).join(result_sections)}

---
*数据来源: DataInterface（自动降级） + 东方财富实时API（板块行情）*
"""
    logger.info(f"[中国市场工具] 数据获取完成，总长度: {len(combined_result)}")
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
        JSON 格式的 ToolResult
    """
    try:
        if not trade_date:
            trade_date = get_current_date_compact()

        logger.info(f"获取龙虎榜数据: 日期{trade_date}, 股票{ts_code}")

        di = DataInterface.get_instance()

        filters = {"limit": 100}
        symbol = None
        if ts_code:
            symbol = ts_code.replace('.SH', '').replace('.SZ', '').replace('.sh', '').replace('.sz', '').zfill(6)

        if symbol:
            result = run_async(di.read("CN", "dragon_tiger", symbol=symbol, filters=filters))
        else:
            result = run_async(di.read("CN", "dragon_tiger", start_date=trade_date, filters=filters))

        data = result.get("data")

        if data:
            if isinstance(data, list):
                records = data[:50]
            else:
                records = [data]

            json_data = json.dumps(records, ensure_ascii=False, default=str)
            return format_tool_result(success_result(data=json_data))

        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            f"无法获取龙虎榜数据: {trade_date}（请先同步 dragon_tiger 数据）"
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
        JSON 格式的 ToolResult
    """
    try:
        if not end_date:
            end_date = get_current_date_compact()
        if not start_date:
            start_date = (now_utc() - timedelta(days=7)).strftime('%Y%m%d')

        logger.info(f"获取大宗交易数据: 日期范围 {start_date}-{end_date}, 股票{code}")

        di = DataInterface.get_instance()

        if code:
            symbol = code.replace('.SH', '').replace('.SZ', '').replace('.sh', '').replace('.sz', '').zfill(6)
            result = run_async(di.read("CN", "block_trade", symbol=symbol))
        else:
            result = run_async(di.read("CN", "block_trade", start_date=start_date, end_date=end_date))

        data = result.get("data")

        if data:
            if isinstance(data, list):
                records = data[:50]
            else:
                records = [data]

            json_data = json.dumps(records, ensure_ascii=False, default=str)
            return format_tool_result(success_result(data=json_data))

        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            "无法获取大宗交易数据（请先同步 block_trade 数据）"
        ))
    except Exception as e:
        logger.error(f"get_block_trade failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            str(e)
        ))
