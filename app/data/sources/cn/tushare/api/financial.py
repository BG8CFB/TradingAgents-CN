"""
Tushare 财务数据 API（利润表/资产负债表/现金流量表/财务指标 + TTM 计算）
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from app.data.sources.base.exceptions import (
    DataNotFoundError,
    DataSourceUnavailableError,
)
from app.data.sources.base.mappers import (
    is_empty_result,
    map_network_exception,
    map_tushare_code,
)
from app.utils.time_utils import now_utc

from .connection import TushareConnection

logger = logging.getLogger(__name__)

_DOMAIN = "financial"


def _safe_float(value) -> Optional[float]:
    """安全浮点数转换"""
    if value is None:
        return None
    try:
        if isinstance(value, str):
            value = value.strip()
            if not value or value.lower() in ("nan", "null", "none", "--"):
                return None
            value = value.replace(",", "").replace("万", "").replace("亿", "")
        if isinstance(value, float) and value != value:
            return None
        return float(value)
    except (ValueError, TypeError, AttributeError):
        return None


def calculate_ttm(income_statements: list, field: str) -> Optional[float]:
    """
    从 Tushare 利润表数据计算 TTM（最近 12 个月）。

    Tushare 利润表数据是年初到报告期的累计值：
      Q1(0331) = 1-3月累计, Q2(0630) = 1-6月累计, ..., Q4(1231) = 1-12月

    TTM = 基准年报 + (本期累计 - 去年同期累计)
    例如 2025Q2 TTM = 2024年报 + (2025Q2 - 2024Q2)
    """
    if not income_statements:
        return None
    try:
        latest = income_statements[0]
        latest_period = latest.get("end_date")
        latest_value = _safe_float(latest.get(field))
        if not latest_period or latest_value is None:
            return None

        month_day = latest_period[4:8]
        if month_day == "1231":
            return latest_value

        latest_year = latest_period[:4]
        last_year = str(int(latest_year) - 1)
        last_year_same_period = last_year + latest_period[4:]

        last_year_same = None
        for stmt in income_statements:
            if stmt.get("end_date") == last_year_same_period:
                last_year_same = stmt
                break
        if not last_year_same:
            return None

        last_year_value = _safe_float(last_year_same.get(field))
        if last_year_value is None:
            return None

        base_period = None
        for stmt in income_statements:
            period = stmt.get("end_date")
            if period and period > last_year_same_period and period[4:8] == "1231":
                base_period = stmt
                break
        if not base_period:
            return None

        base_value = _safe_float(base_period.get(field))
        if base_value is None:
            return None

        ttm = base_value + (latest_value - last_year_value)
        logger.debug(
            f"TTM: {base_period.get('end_date')}({base_value:.2f}) + "
            f"({latest_period}({latest_value:.2f}) - {last_year_same_period}({last_year_value:.2f})) = {ttm:.2f}"
        )
        return ttm
    except Exception as e:
        logger.warning(f"TTM 计算异常: {e}")
        return None


def _determine_report_type(report_period: str) -> str:
    if not report_period:
        return "quarterly"
    try:
        return "annual" if report_period[4:8] == "1231" else "quarterly"
    except Exception as e:
        logger.debug(f"判断报告类型失败: {e}")
        return "quarterly"


async def fetch_financial_data(
    conn: TushareConnection,
    ts_code: str,
    period: str = None,
    limit: int = 8,
    start_date: str = None,
    end_date: str = None,
) -> Optional[Dict[str, Any]]:
    """获取多表联合财务数据（income/balancesheet/cashflow/fina_indicator/fina_mainbz）

    日期过滤策略：Tushare 财务接口不支持按日期范围直接查询，只支持单 period
    或 limit 取最近 N 期。这里先按 limit 拉取较新数据，再在内存中按
    start_date/end_date 对报告期（end_date 字段）做过滤，避免冗余返回。
    """
    if not conn.is_available():
        return None

    query_params: Dict[str, Any] = {"ts_code": ts_code, "limit": limit}
    if period:
        query_params["period"] = period

    financial_data: Dict[str, Any] = {}

    tables = [
        ("income_statement", "income"),
        ("balance_sheet", "balancesheet"),
        ("cashflow_statement", "cashflow"),
        ("financial_indicators", "fina_indicator"),
        ("main_business", "fina_mainbz"),
    ]

    # 补充表：失败不影响核心校验，仅追加到 raw_data
    supplementary_tables = [
        ("forecast", "forecast"),       # 业绩预告
        ("express", "express"),         # 业绩快报
        ("dividend", "dividend"),       # 分红送股
        ("fina_audit", "fina_audit"),   # 审计意见
        ("disclosure_date", "disclosure_date"),  # 财报披露日期
    ]

    # 致命异常：一旦遇到立即透传（鉴权/积分/网络）
    fatal_error: Optional[Exception] = None

    for i, (key, api_name) in enumerate(tables):
        # 请求间隔控制：避免触发限流（稳定 100-200次/分钟）
        if i > 0:
            await asyncio.sleep(0.3)

        # 重试机制：并发场景下自建源可能瞬时返回空，重试 2 次
        df = None
        for attempt in range(3):
            try:
                df = await asyncio.to_thread(getattr(conn.api, api_name), **query_params)
            except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
                raise map_network_exception(exc, "tushare", _DOMAIN)
            except Exception as exc:
                error_code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
                mapped = map_tushare_code(error_code, "tushare", _DOMAIN, str(exc))
                if mapped is not None:
                    raise mapped
                if api_name != "fina_mainbz":
                    logger.warning(f"Tushare 获取 {api_name} 失败: {exc}")
                    if fatal_error is None:
                        fatal_error = DataSourceUnavailableError(
                            "tushare", _DOMAIN, f"{api_name}: {exc}"
                        )
                break
            if df is not None and not df.empty:
                break
            if attempt < 2:
                wait = 2.0 * (attempt + 1)
                logger.warning(
                    f"Tushare {api_name} 返回空 (attempt {attempt+1}/3)，"
                    f"ts_code={ts_code}，等待 {wait}s 重试"
                )
                await asyncio.sleep(wait)

        if df is not None and not df.empty:
            records = df.to_dict("records")
            # 按报告期（end_date）做内存过滤，避免返回 start_date/end_date 范围外的冗余数据
            if start_date or end_date:
                records = _filter_by_report_period(records, start_date, end_date)
            if records:
                financial_data[key] = records

    # 补充表：失败不影响核心校验，仅追加到 raw_data
    for key, api_name in supplementary_tables:
        await asyncio.sleep(0.3)
        try:
            # 各 API 参数不同，按接口分别构造
            if api_name == "dividend":
                params = {"ts_code": ts_code}
            elif api_name == "fina_audit":
                params = {"ts_code": ts_code}
                if period:
                    params["period"] = period
            elif api_name == "disclosure_date":
                params = {"ts_code": ts_code}
                if period:
                    params["end_date"] = period
            else:
                # forecast / express：支持 ts_code + period + limit
                params = {"ts_code": ts_code, "limit": limit}
                if period:
                    params["period"] = period
            df = await asyncio.to_thread(getattr(conn.api, api_name), **params)
            if df is not None and not df.empty:
                records = df.to_dict("records")
                if (start_date or end_date) and api_name not in ("dividend", "disclosure_date"):
                    records = _filter_by_report_period(records, start_date, end_date)
                if records:
                    financial_data[key] = records
        except Exception as exc:
            logger.debug(f"Tushare 补充表 {api_name} 获取失败（忽略）: {exc}")

    # 核心表校验：income_statement 是 TTM 计算 / 标准化必依赖的表。
    # 若缺失则不能继续标准化（否则会输出 revenue/net_profit 全空的半残数据）。
    if "income_statement" not in financial_data:
        if fatal_error is not None:
            raise fatal_error
        raise DataSourceUnavailableError(
            "tushare", _DOMAIN, f"ts_code={ts_code} 缺少核心表 income_statement"
        )

    if not financial_data:
        # 没有任何表成功：若扫描过程中有致命异常则透传，否则视为无数据
        if fatal_error is not None:
            raise fatal_error
        logger.warning(f"Tushare 财务数据为空: ts_code={ts_code}")
        raise DataNotFoundError("tushare", _DOMAIN, f"ts_code={ts_code} 无数据")

    return _standardize(financial_data, ts_code)


def _filter_by_report_period(
    records: List[Dict[str, Any]], start_date: str, end_date: str
) -> List[Dict[str, Any]]:
    """按报告期 end_date 过滤 Tushare 财务记录。

    end_date 格式为 YYYYMMDD（Tushare 原始格式），start_date/end_date 可能是
    YYYY-MM-DD 或 YYYYMMDD，统一去掉分隔符后做字符串比较。
    """
    start = str(start_date).replace("-", "") if start_date else None
    end = str(end_date).replace("-", "") if end_date else None
    result = []
    for rec in records:
        rp = str(rec.get("end_date") or rec.get("report_period") or "")
        rp = rp.replace("-", "")
        if start and rp < start:
            continue
        if end and rp > end:
            continue
        result.append(rec)
    return result


def _standardize(financial_data: Dict[str, Any], ts_code: str) -> Dict[str, Any]:
    """标准化 Tushare 财务数据"""
    def _first(key):
        records = financial_data.get(key, [])
        return records[0] if records else {}

    latest_income = _first("income_statement")
    latest_balance = _first("balance_sheet")
    latest_cashflow = _first("cashflow_statement")
    latest_indicator = _first("financial_indicators")

    symbol = ts_code.split(".")[0] if "." in ts_code else ts_code
    report_period = (
        latest_income.get("end_date")
        or latest_balance.get("end_date")
        or latest_cashflow.get("end_date")
    )
    ann_date = (
        latest_income.get("ann_date")
        or latest_balance.get("ann_date")
        or latest_cashflow.get("ann_date")
    )

    income_stmts = financial_data.get("income_statement", [])
    revenue_ttm = calculate_ttm(income_stmts, "revenue")
    net_profit_ttm = calculate_ttm(income_stmts, "n_income_attr_p")

    # 补充数据：业绩预告、业绩快报、分红送股
    latest_forecast = _first("forecast")
    latest_express = _first("express")
    latest_dividend = _first("dividend")

    return {
        "symbol": symbol,
        "ts_code": ts_code,
        "report_period": report_period,
        "ann_date": ann_date,
        "report_type": _determine_report_type(report_period),
        "revenue": _safe_float(latest_income.get("revenue")),
        "revenue_ttm": revenue_ttm,
        "net_income": _safe_float(latest_income.get("n_income")),
        "net_profit": _safe_float(latest_income.get("n_income_attr_p")),
        "net_profit_ttm": net_profit_ttm,
        "oper_cost": _safe_float(latest_income.get("oper_cost")),
        "total_assets": _safe_float(latest_balance.get("total_assets")),
        "total_liab": _safe_float(latest_balance.get("total_liab")),
        "total_equity": _safe_float(latest_balance.get("total_hldr_eqy_exc_min_int")),
        "n_cashflow_act": _safe_float(latest_cashflow.get("n_cashflow_act")),
        "roe": _safe_float(latest_indicator.get("roe")),
        "roa": _safe_float(latest_indicator.get("roa")),
        "gross_margin": _safe_float(latest_indicator.get("grossprofit_margin")),
        "netprofit_margin": _safe_float(latest_indicator.get("netprofit_margin")),
        "debt_to_assets": _safe_float(latest_indicator.get("debt_to_assets")),
        "current_ratio": _safe_float(latest_indicator.get("current_ratio")),
        "quick_ratio": _safe_float(latest_indicator.get("quick_ratio")),
        "eps": _safe_float(latest_indicator.get("eps")),
        "bps": _safe_float(latest_indicator.get("bps")),
        # 业绩预告
        "forecast_type": latest_forecast.get("type"),
        "forecast_min": _safe_float(latest_forecast.get("p_change_min")),
        "forecast_max": _safe_float(latest_forecast.get("p_change_max")),
        "forecast_summary": latest_forecast.get("summary"),
        # 业绩快报
        "express_revenue": _safe_float(latest_express.get("revenue")),
        "express_net_profit": _safe_float(latest_express.get("net_profit")),
        "express_roe": _safe_float(latest_express.get("roe")),
        # 分红送股
        "cash_div": _safe_float(latest_dividend.get("cash_div")),
        "stock_div": _safe_float(latest_dividend.get("stock_div")),
        "stock_bo": _safe_float(latest_dividend.get("stock_bo")),
        "raw_data": {k: v for k, v in financial_data.items()},
        "data_source": "tushare",
        "updated_at": now_utc(),
    }


async def fetch_forecast(
    conn: TushareConnection,
    ts_code: str = None,
    ann_date: str = None,
    start_date: str = None,
    end_date: str = None,
    limit: int = 8,
) -> Optional[pd.DataFrame]:
    """获取业绩预告数据"""
    if not conn.is_available():
        return None

    kwargs = {"limit": limit}
    if ts_code:
        kwargs["ts_code"] = ts_code
    if ann_date:
        kwargs["ann_date"] = str(ann_date).replace("-", "")
    elif start_date:
        kwargs["start_date"] = str(start_date).replace("-", "")
        kwargs["end_date"] = str(end_date or start_date).replace("-", "")

    try:
        df = await asyncio.to_thread(conn.api.forecast, **kwargs)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "tushare", "forecast")
    except Exception as exc:
        error_code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
        mapped = map_tushare_code(error_code, "tushare", "forecast", str(exc))
        if mapped is not None:
            raise mapped
        raise DataSourceUnavailableError("tushare", "forecast", str(exc))

    if is_empty_result(df):
        raise DataNotFoundError("tushare", "forecast", f"{kwargs} 无数据")

    logger.info(f"Tushare 业绩预告: {len(df)} 条")
    return df


async def fetch_express(
    conn: TushareConnection,
    ts_code: str = None,
    ann_date: str = None,
    start_date: str = None,
    end_date: str = None,
    limit: int = 8,
) -> Optional[pd.DataFrame]:
    """获取业绩快报数据"""
    if not conn.is_available():
        return None

    kwargs = {"limit": limit}
    if ts_code:
        kwargs["ts_code"] = ts_code
    if ann_date:
        kwargs["ann_date"] = str(ann_date).replace("-", "")
    elif start_date:
        kwargs["start_date"] = str(start_date).replace("-", "")
        kwargs["end_date"] = str(end_date or start_date).replace("-", "")

    try:
        df = await asyncio.to_thread(conn.api.express, **kwargs)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "tushare", "express")
    except Exception as exc:
        error_code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
        mapped = map_tushare_code(error_code, "tushare", "express", str(exc))
        if mapped is not None:
            raise mapped
        raise DataSourceUnavailableError("tushare", "express", str(exc))

    if is_empty_result(df):
        raise DataNotFoundError("tushare", "express", f"{kwargs} 无数据")

    logger.info(f"Tushare 业绩快报: {len(df)} 条")
    return df
