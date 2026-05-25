"""
AKShare 每日指标 API（PE/PB/PS/市值/换手率等）

数据来源：百度股市通（stock_zh_valuation_baidu）+ 东方财富（stock_zh_a_hist）
- 百度股市通提供：总市值、PE(TTM)、PE(静)、PB、市现率
- 东方财富行情提供：换手率
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


async def fetch_daily_indicators_by_symbol(
    code: str, start_date: str = None, end_date: str = None
) -> Optional[pd.DataFrame]:
    """
    获取单只股票每日估值指标（PE/PB/PS/总市值/换手率）。

    通过百度股市通获取估值数据，通过东方财富行情获取换手率，
    合并为一个 DataFrame 返回。
    """
    try:
        import akshare as ak

        # 确定时间范围
        period = _determine_period(start_date, end_date)

        # 并发获取 5 个指标 + 换手率
        indicators = ["总市值", "市盈率(TTM)", "市净率"]
        fetch_tasks = []

        for indicator in indicators:
            fetch_tasks.append(_fetch_valuation_safe(ak, code, indicator, period))

        # 换手率从行情数据获取
        fetch_tasks.append(_fetch_turnover_from_quotes(ak, code, start_date, end_date))

        results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        # 解析结果
        mv_df = results[0] if not isinstance(results[0], Exception) else None
        pe_df = results[1] if not isinstance(results[1], Exception) else None
        pb_df = results[2] if not isinstance(results[2], Exception) else None
        turnover_df = results[3] if not isinstance(results[3], Exception) else None

        # 以总市值的时间序列为基准进行合并
        base_df = mv_df if mv_df is not None and not mv_df.empty else None
        if base_df is None:
            # 如果总市值获取失败，用PE的日期
            base_df = pe_df if pe_df is not None and not pe_df.empty else None
        if base_df is None:
            logger.warning(f"AKShare 每日指标: {code} 无法获取任何估值数据")
            return None

        merged = base_df[["date"]].copy()

        if mv_df is not None and not mv_df.empty:
            merged = merged.merge(mv_df, on="date", how="left")
        if pe_df is not None and not pe_df.empty:
            merged = merged.merge(pe_df, on="date", how="left")
        if pb_df is not None and not pb_df.empty:
            merged = merged.merge(pb_df, on="date", how="left")
        if turnover_df is not None and not turnover_df.empty:
            merged = merged.merge(turnover_df, on="date", how="left")

        if merged.empty:
            return None

        # 添加 symbol 列
        merged["symbol"] = code

        # 日期过滤
        merged["date"] = merged["date"].astype(str)
        if start_date:
            start_clean = start_date.replace("-", "")
            merged = merged[merged["date"].str.replace("-", "") >= start_clean]
        if end_date:
            end_clean = end_date.replace("-", "")
            merged = merged[merged["date"].str.replace("-", "") <= end_clean]

        logger.info(f"AKShare 每日指标: {code} {len(merged)} 条")
        return merged.reset_index(drop=True)

    except Exception as e:
        logger.error(f"AKShare 获取每日指标失败 {code}: {e}")
        return None


async def _fetch_valuation_safe(ak_module, code: str, indicator: str, period: str) -> Optional[pd.DataFrame]:
    """安全获取百度估值数据，失败返回 None。"""
    try:
        df = await asyncio.to_thread(
            ak_module.stock_zh_valuation_baidu,
            symbol=code,
            indicator=indicator,
            period=period,
        )
        if df is None or df.empty:
            return None

        col_name = _indicator_to_column(indicator)
        result = df[["date", "value"]].copy()
        result.columns = ["date", col_name]
        return result
    except Exception as e:
        logger.debug(f"AKShare 百度估值 {code}/{indicator} 获取失败: {e}")
        return None


async def _fetch_turnover_from_quotes(
    ak_module, code: str, start_date: str = None, end_date: str = None
) -> Optional[pd.DataFrame]:
    """从东方财富行情数据提取换手率。"""
    try:
        start = (start_date or "20200101").replace("-", "")
        end = (end_date or "20991231").replace("-", "")

        df = await asyncio.to_thread(
            ak_module.stock_zh_a_hist,
            symbol=code,
            period="daily",
            start_date=start,
            end_date=end,
            adjust="",
        )
        if df is None or df.empty:
            return None

        # stock_zh_a_hist 返回中文字段名
        result = df[["日期", "换手率"]].copy()
        result.columns = ["date", "turnover_rate"]
        return result
    except Exception as e:
        logger.debug(f"AKShare 换手率 {code} 获取失败: {e}")
        return None


def _indicator_to_column(indicator: str) -> str:
    """将百度估值指标名映射为内部字段名。"""
    mapping = {
        "总市值": "total_mv",
        "市盈率(TTM)": "pe_ttm",
        "市盈率(静)": "pe",
        "市净率": "pb",
        "市现率": "ps_ttm",
    }
    return mapping.get(indicator, indicator)


def _determine_period(start_date: str = None, end_date: str = None) -> str:
    """根据日期范围确定百度 API 的 period 参数。"""
    if not start_date and not end_date:
        return "近一年"

    from datetime import datetime
    try:
        end = datetime.strptime(end_date or "20991231", "%Y%m%d") if end_date else datetime.now()
        start = datetime.strptime(start_date or "20200101", "%Y%m%d") if start_date else datetime(2020, 1, 1)
    except (ValueError, TypeError):
        return "近一年"

    delta_days = (end - start).days
    if delta_days > 365 * 8:
        return "全部"
    elif delta_days > 365 * 4:
        return "近十年"
    elif delta_days > 365 * 2:
        return "近五年"
    elif delta_days > 365:
        return "近三年"
    else:
        return "近一年"
