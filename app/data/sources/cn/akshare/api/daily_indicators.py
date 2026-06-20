"""
AKShare 每日指标 API（PE/PB/PS/市值/换手率等）

数据来源：百度股市通（stock_zh_valuation_baidu）+ 东方财富（stock_zh_a_hist）
- 百度股市通提供：总市值、PE(TTM)、PE(静)、PB、市现率
- 东方财富行情提供：换手率
"""
import asyncio
import logging
from typing import Dict, Optional

import pandas as pd

from app.data.sources.base.exceptions import (
    DataFormatError,
    DataNotFoundError,
    DataSourceUnavailableError,
)
from app.data.sources.base.mappers import map_network_exception

logger = logging.getLogger(__name__)

_DOMAIN = "daily_indicators"


async def fetch_daily_indicators_by_symbol(
    code: str, start_date: str = None, end_date: str = None
) -> pd.DataFrame:
    """
    获取单只股票每日估值指标（PE/PB/PS/总市值/换手率）。

    通过百度股市通获取估值数据，通过东方财富行情获取换手率，
    合并为一个 DataFrame 返回。

    Raises:
        NetworkError: 网络/超时异常（可重试）
        DataFormatError: AKShare 返回结构异常（不可重试）
        DataNotFoundError: 所有子源均无数据（不可重试）
        DataSourceUnavailableError: 其他未知异常
    """
    try:
        import akshare as ak

        # 确定时间范围
        period = _determine_period(start_date, end_date)

        # 用 dict 组织并发任务，避免依赖 results 的位置索引
        # key 为输出列名（与 _indicator_to_column 一致），value 为协程
        task_map: Dict[str, "asyncio.Future"] = {
            "total_mv": _fetch_valuation_safe(ak, code, "总市值", period),
            "pe_ttm": _fetch_valuation_safe(ak, code, "市盈率(TTM)", period),
            "pb": _fetch_valuation_safe(ak, code, "市净率", period),
            "turnover_rate": _fetch_turnover_from_quotes(ak, code, start_date, end_date),
        }

        # 并发执行；return_exceptions=True 让单个子源失败不致整批抛错
        keys = list(task_map.keys())
        raw_results = await asyncio.gather(*task_map.values(), return_exceptions=True)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        # 网络异常：可重试
        raise map_network_exception(exc, "akshare", _DOMAIN)
    except (KeyError, IndexError, AttributeError, ValueError) as exc:
        # 数据格式异常：AKShare 返回结构不符合预期，不可重试
        raise DataFormatError("akshare", _DOMAIN, f"code={code}: {exc}")
    except Exception as exc:
        # 其他未知异常
        raise DataSourceUnavailableError("akshare", _DOMAIN, f"code={code}: {exc}")

    # 把 results 与 key 关联起来（Exception 转为 None）
    results: Dict[str, Optional[pd.DataFrame]] = {
        k: (None if isinstance(r, Exception) else r)
        for k, r in zip(keys, raw_results)
    }

    mv_df = results["total_mv"]
    pe_df = results["pe_ttm"]
    pb_df = results["pb"]
    turnover_df = results["turnover_rate"]

    # 以总市值的时间序列为基准进行合并
    base_df = mv_df if mv_df is not None and not mv_df.empty else None
    if base_df is None:
        # 如果总市值获取失败，用PE的日期
        base_df = pe_df if pe_df is not None and not pe_df.empty else None
    if base_df is None:
        # 所有子源都失败 → 视为无数据
        logger.warning(f"AKShare 每日指标: {code} 无法获取任何估值数据")
        raise DataNotFoundError("akshare", _DOMAIN, f"code={code} 所有子源均无数据")

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
        raise DataNotFoundError("akshare", _DOMAIN, f"code={code} 合并后无数据")

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


async def _fetch_valuation_safe(ak_module, code: str, indicator: str, period: str) -> Optional[pd.DataFrame]:
    """安全获取百度估值数据，失败返回 None。"""
    try:
        from app.data.sources.cn.akshare.api.anti_scraping import wait_rate_limit

        def _fetch():
            wait_rate_limit()
            return ak_module.stock_zh_valuation_baidu(
                symbol=code, indicator=indicator, period=period,
            )

        df = await asyncio.to_thread(_fetch)
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

        from app.data.sources.cn.akshare.api.anti_scraping import wait_rate_limit

        def _fetch():
            wait_rate_limit()
            return ak_module.stock_zh_a_hist(
                symbol=code, period="daily",
                start_date=start, end_date=end, adjust="",
            )

        df = await asyncio.to_thread(_fetch)
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
