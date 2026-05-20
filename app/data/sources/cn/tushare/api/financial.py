"""
Tushare 财务数据 API（利润表/资产负债表/现金流量表/财务指标 + TTM 计算）
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

from app.utils.time_utils import now_utc

from .connection import TushareConnection

logger = logging.getLogger(__name__)


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
    except Exception:
        return "quarterly"


async def fetch_financial_data(
    conn: TushareConnection,
    ts_code: str,
    period: str = None,
    limit: int = 4,
) -> Optional[Dict[str, Any]]:
    """获取多表联合财务数据（income/balancesheet/cashflow/fina_indicator/fina_mainbz）"""
    if not conn.is_available():
        return None

    try:
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

        for key, api_name in tables:
            try:
                df = await asyncio.to_thread(getattr(conn.api, api_name), **query_params)
                if df is not None and not df.empty:
                    financial_data[key] = df.to_dict("records")
            except Exception as e:
                if api_name != "fina_mainbz":
                    logger.warning(f"Tushare 获取 {api_name} 失败: {e}")

        if not financial_data:
            return None

        return _standardize(financial_data, ts_code)

    except Exception as e:
        logger.error(f"Tushare 获取财务数据失败 {ts_code}: {e}")
        return None


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
        "raw_data": {k: v for k, v in financial_data.items()},
        "data_source": "tushare",
        "updated_at": now_utc(),
    }
