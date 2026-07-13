"""
板块/行业工具 - 申万行业指数、同花顺板块、板块资金流
"""
import json
import logging
import re
from typing import Optional
from datetime import timedelta, date

from app.utils.time_utils import now_utc, get_current_date, get_current_date_compact
from app.engine.tools.common.tool_result import success_result, error_result, format_tool_result, ErrorCodes
from app.engine.tools.common.format import format_result
from app.data.core.interface import DataInterface
from app.core.async_utils import run_async

logger = logging.getLogger(__name__)


# 申万旧行业分类 -> 申万2021 行业名称 的高置信映射（仅用于把股票 industry 名对齐到 sw_daily）。
# 只收录“旧名 ≠ 2021 名”且确认无误的条目；无法可靠匹配时返回 None，绝不返回错误行业。
_SW_OLD_TO_2021 = {
    "元器件": "光学光电子",
    "光学光电子": "光学光电子",
}


async def _sw_daily_name_to_code() -> dict:
    """返回 sw_daily 全部 {行业名称: ts_code} 映射。"""
    di = DataInterface.get_instance()
    res = await di.read("CN", "sw_daily", start_date="19700101", end_date="20991231")
    raw = res.get("data") or []
    rows = raw if isinstance(raw, list) else ([raw] if raw else [])
    return {r["name"]: r["ts_code"] for r in rows if r.get("name") and r.get("ts_code")}


def _as_list(data):
    """将 read 返回的 data（可能是 dict 单条或 list）统一成 list。"""
    if data is None:
        return []
    if isinstance(data, list):
        return data
    return [data]


async def _resolve_sw_index_for_stock(symbol: str) -> Optional[str]:
    """把 6 位股票代码解析为其所属申万行业指数的 ts_code。

    通过 basic_info.industry -> sw_daily 名称匹配（含旧->2021 映射）。
    无法可靠匹配时返回 None（避免把股票映射到错误行业，产生逻辑矛盾）。
    """
    di = DataInterface.get_instance()
    basic = await di.read("CN", "basic_info", symbol=symbol)
    rows = _as_list(basic.get("data"))
    industry = rows[0].get("industry") if rows else None
    if not industry:
        return None
    name_to_code = await _sw_daily_name_to_code()
    target = _SW_OLD_TO_2021.get(industry, industry)
    if target in name_to_code:
        return name_to_code[target]
    # 归一化（去除罗马数字 Ⅰ/Ⅱ/Ⅲ 与空格）后再试一次
    norm = lambda s: re.sub(r"[ ⅠⅡⅢ\s]", "", str(s))
    norm_target = norm(target)
    for k, v in name_to_code.items():
        if norm(k) == norm_target:
            return v
    return None


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
    """获取申万行业指数日行情（板块强弱分析）。

    支持传入股票代码（6 位）：自动解析其所属申万行业指数后再查询。

    未指定日期时默认取“最近交易日”而非“今天”：避免周末/未同步日直接查当日
    返回空、进而回退到 tushare 实时接口导致“获取失败”；若最近交易日仍为空，
    再回退到最近 30 天窗口内的最新一条。

    sw_daily 以指数代码落库：symbol 字段为去后缀的 6 位码（如 801084），
    ts_code 字段带后缀（如 801084.SI）。精确查询时一律用“去后缀码”作为 symbol，
    避免一次性拉取全市场指数再过滤（get_by_date_range 有 1000 条上限）。
    """
    try:
        auto_date = False
        if not trade_date and not start_date:
            auto_date = True
            try:
                td = run_async(get_latest_trade_day("CN"))
            except Exception:
                td = None
            trade_date = (td or date.today()).strftime("%Y%m%d")
        trade_date = str(trade_date).replace("-", "") if trade_date else None
        if start_date:
            start_date = str(start_date).replace("-", "")
        if end_date:
            end_date = str(end_date).replace("-", "")

        # 股票代码 -> 申万行业指数代码（sw_daily 按指数代码存储，非股票代码）
        if ts_code and re.fullmatch(r"\d{6}", ts_code):
            resolved = run_async(_resolve_sw_index_for_stock(ts_code))
            if resolved:
                ts_code = resolved

        # 精确查询用的 symbol：指数代码去后缀（801084.SI -> 801084）
        query_symbol = str(ts_code).split(".")[0] if ts_code else None

        di = DataInterface.get_instance()

        def _read(target_td, s, e):
            return run_async(di.read("CN", "sw_daily", symbol=query_symbol,
                                     start_date=s or target_td,
                                     end_date=e or target_td)).get("data")

        # 1) 最近交易日精确查
        rows = _read(trade_date, start_date, end_date)
        # 2) 自动选日仍为空时，回退最近 30 天窗口内的最新一条
        if not rows and auto_date:
            end = date.today()
            start = end - timedelta(days=30)
            rows = _read(None, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
            if rows and isinstance(rows, list):
                import pandas as pd
                all_df = pd.DataFrame(rows)
                if "trade_date" in all_df.columns:
                    latest_day = all_df["trade_date"].astype(str).max()
                    rows = all_df[all_df["trade_date"].astype(str) == latest_day].to_dict("records")

        if rows:
            import pandas as pd
            df = pd.DataFrame(rows) if isinstance(rows, list) else rows
            return format_tool_result(success_result(format_result(df, "申万行业指数")))

        # 回退到 tushare 直接获取（仅在 MongoDB 确无数据时使用）
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
