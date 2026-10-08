"""
Tushare 财务数据 API（利润表/资产负债表/现金流量表/财务指标 + TTM 计算）
"""
import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from app.data.sources.base.exceptions import (
    DataNotFoundError,
    DataSourceUnavailableError,
)
from app.data.sources.base.mappers import (
    map_network_exception,
    map_tushare_code,
)
from app.data.sources.tushare_common.caller import call_tushare_paged
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


def _date_key(value: Any) -> Optional[str]:
    """Validate a source date, without inventing a disclosure date from a period."""
    if value is None or pd.isna(value):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip().replace("-", "")
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return datetime.strptime(text, "%Y%m%d").strftime("%Y%m%d")
    except ValueError:
        return None


def _scope(record: Dict[str, Any]) -> Optional[str]:
    value = record.get("report_type")
    if value is None or pd.isna(value):
        return None
    # DataFrame construction can coerce integral source codes to floats.
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip() or None


def _disclosure_date(record: Dict[str, Any]) -> Optional[str]:
    """A contributed row is usable no earlier than both source disclosure dates."""
    dates = []
    for field in ("ann_date", "f_ann_date"):
        value = record.get(field)
        if value is None or pd.isna(value) or value == "":
            continue
        parsed = _date_key(value)
        if parsed is None:
            return None
        dates.append(parsed)
    period = _date_key(record.get("end_date"))
    if not dates or period is None or min(dates) < period:
        return None
    return max(dates)


def _latest_disclosed(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Choose deterministically by actual disclosure, not API row order."""
    return max(records, key=lambda row: _disclosure_date(row) or "") if records else {}


def _disclosure(record: Dict[str, Any], *, included: bool) -> Dict[str, Any]:
    return {
        "report_period": _date_key(record.get("end_date")),
        "announce_date": _disclosure_date(record),
        "reported_announce_date": _date_key(record.get("ann_date")),
        "actual_announce_date": _date_key(record.get("f_ann_date")),
        "report_type": _scope(record),
        "included": included,
    }


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

    # 致命异常：一旦遇到立即透传（鉴权/积分/网络）
    fatal_error: Optional[Exception] = None

    for key, api_name in tables:
        try:
            df = await asyncio.to_thread(getattr(conn.api, api_name), **query_params)
        except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
            # 网络异常：整批请求视为失败
            raise map_network_exception(exc, "tushare", _DOMAIN)
        except Exception as exc:
            error_code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
            mapped = map_tushare_code(error_code, "tushare", _DOMAIN, str(exc))
            if mapped is not None:
                # 鉴权/积分/限流类异常：致命，直接透传
                raise mapped
            # 其他未知异常：fina_mainbz 缺失属正常（部分公司无主营构成），其余记 warning
            if api_name != "fina_mainbz":
                logger.warning(f"Tushare 获取 {api_name} 失败: {exc}")
                if fatal_error is None:
                    fatal_error = DataSourceUnavailableError(
                        "tushare", _DOMAIN, f"{api_name}: {exc}"
                    )
            continue

        if df is not None and not df.empty:
            records = df.to_dict("records")
            # 按报告期（end_date）做内存过滤，避免返回 start_date/end_date 范围外的冗余数据
            if start_date or end_date:
                records = _filter_by_report_period(records, start_date, end_date)
            if records:
                financial_data[key] = records

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
    income_stmts = financial_data.get("income_statement", [])
    periods = [_date_key(row.get("end_date")) for row in income_stmts]
    report_period = max((period for period in periods if period), default=None)
    current_income = [row for row in income_stmts
                      if _date_key(row.get("end_date")) == report_period]
    scopes = {_scope(row) for row in current_income}
    # Different statement scopes cannot be spliced or selected by response order.
    scope = next(iter(scopes)) if len(scopes) == 1 and None not in scopes else None
    latest_income = _latest_disclosed(current_income) if scope else {}

    def _matching(key, *, indicator=False):
        rows = [row for row in financial_data.get(key, [])
                if _date_key(row.get("end_date")) == report_period
                and (indicator or (scope and _scope(row) == scope))]
        row = _latest_disclosed(rows)
        return row if _disclosure_date(row) else {}

    # Do not attach another period's latest table to the income period.
    latest_balance = _matching("balance_sheet")
    latest_cashflow = _matching("cashflow_statement")
    latest_indicator = _matching("financial_indicators", indicator=True)
    if not _disclosure_date(latest_income):
        latest_income = {}

    symbol = ts_code.split(".")[0] if "." in ts_code else ts_code
    contributors = {"income": latest_income, "balance": latest_balance,
                    "cashflow": latest_cashflow, "indicator": latest_indicator}
    dates = [_disclosure_date(row) for row in contributors.values() if row]
    # TTM may involve a later correction to a prior-period statement. Retain that
    # date in the aggregate bound too, and never mix its statement scope.
    ttm_rows = [row for row in income_stmts if scope and _scope(row) == scope
                and _disclosure_date(row) and _date_key(row.get("end_date"))
                and _date_key(row.get("end_date")) <= (report_period or "")]
    by_period = {}
    for row in ttm_rows:
        period = _date_key(row["end_date"])
        by_period[period] = _latest_disclosed([by_period[period], row]) if period in by_period else row
    ttm_rows = [dict(by_period[period], end_date=period)
                for period in sorted(by_period, reverse=True)]
    revenue_ttm = calculate_ttm(ttm_rows, "revenue") if latest_income else None
    net_profit_ttm = calculate_ttm(ttm_rows, "n_income_attr_p") if latest_income else None
    if revenue_ttm is not None or net_profit_ttm is not None:
        dates.extend(_disclosure_date(row) for row in ttm_rows)
    ann_date = max(dates) if dates else None

    return {
        "symbol": symbol,
        "ts_code": ts_code,
        "report_period": report_period,
        "ann_date": ann_date,
        "report_type": scope,
        "source_disclosures": {key: _disclosure(row, included=bool(row))
                               for key, row in contributors.items()} | {
            "ttm_income": [_disclosure(row, included=True) for row in ttm_rows]
            if revenue_ttm is not None or net_profit_ttm is not None else [],
        },
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


# ── 按报告期批量模式（全市场，同步任务 __all__ 路径专用）─────────────
# 逐 symbol 模式（fetch_financial_data）对全市场 ~5400 股 × 5 表 ≈ 2.7 万次
# 调用，在 200/min 限流下必然熔断；fina_indicator/income 均支持 period 参数
# 按报告期一次拉全市场，5 期 × 2 接口 = 10 次调用即覆盖全市场最近 5 期。
# 注意：period-only 全市场查询受 tushare 积分档限制（低档要求必填
# ts_code），失败时回退链自动落 AKShare 批量（东财业绩报表+资产负债表）。
# 报告期窗口函数 recent_report_periods 位于 cn/reporting.py（两源共享）。

_FINA_INDICATOR_PERIOD_FIELDS = (
    "ts_code,ann_date,end_date,roe,roa,grossprofit_margin,"
    "netprofit_margin,debt_to_assets,current_ratio,eps,bps"
)
_INCOME_PERIOD_FIELDS = (
    "ts_code,ann_date,f_ann_date,end_date,report_type,total_revenue,n_income"
)


def _merge_period_financials(
    indicators: pd.DataFrame, incomes: Optional[pd.DataFrame], period: str
) -> pd.DataFrame:
    """Merge only same-period rows, preserving a safe aggregate disclosure bound."""
    expected_period = _date_key(period)
    indicator_rows = indicators.to_dict("records")
    income_rows = incomes.to_dict("records") if incomes is not None else []
    grouped = {}
    for row in indicator_rows:
        if row.get("ts_code") and expected_period and _date_key(row.get("end_date")) == expected_period:
            grouped.setdefault(row["ts_code"], []).append(row)
    income_by_symbol = {}
    for row in income_rows:
        if row.get("ts_code") and expected_period and _date_key(row.get("end_date")) == expected_period:
            income_by_symbol.setdefault(row["ts_code"], []).append(row)
    merged = []
    for symbol, rows in grouped.items():
        indicator = _latest_disclosed(rows)
        result = dict(indicator)
        matches = income_by_symbol.get(symbol, [])
        scopes = {_scope(row) for row in matches}
        scope = next(iter(scopes)) if len(scopes) == 1 and None not in scopes else None
        income = _latest_disclosed(matches) if scope else {}
        indicator_date = _disclosure_date(indicator)
        income_date = _disclosure_date(income)
        included = bool(income_date and indicator_date)
        result["total_revenue"] = income.get("total_revenue") if included else None
        result["n_income"] = income.get("n_income") if included else None
        result["report_type"] = scope if included else None
        # Clear all adapter fallback aliases: an unknown merged date must not
        # accidentally fall back to the indicator's earlier ann_date.
        safe_date = max(indicator_date, income_date) if included else indicator_date
        result.update(ann_date=safe_date, f_ann_date=None, announce_date=safe_date,
                      statement_type="indicator")
        result["source_disclosures"] = {
            "indicator": _disclosure(indicator, included=True),
            "income": _disclosure(income, included=included),
        }
        merged.append(result)
    return pd.DataFrame(merged)


async def fetch_financial_indicator_by_period(
    conn: TushareConnection, period: str
) -> Optional[pd.DataFrame]:
    """fina_indicator 按报告期一次拉全市场（分页）。"""
    return await call_tushare_paged(
        conn, "fina_indicator", "tushare", _DOMAIN, f"period={period}",
        period=period, fields=_FINA_INDICATOR_PERIOD_FIELDS,
    )


async def fetch_income_by_period(
    conn: TushareConnection, period: str
) -> Optional[pd.DataFrame]:
    """income 利润表按报告期一次拉全市场（分页，补营收/净利润供同比）。"""
    return await call_tushare_paged(
        conn, "income", "tushare", _DOMAIN, f"period={period}",
        period=period, fields=_INCOME_PERIOD_FIELDS,
    )


async def fetch_financial_data_batch(
    conn: TushareConnection, periods: List[str]
) -> Optional[pd.DataFrame]:
    """批量财务数据：逐期 indicator 为基表左连 income → 一报告期一行合并记录。

    列名保持 Tushare 原始口径（grossprofit_margin/debt_to_assets/n_income
    等），供 adapt_financial_data 统一转换；statement_type 显式为
    "indicator"（合并记录同时含 income 列，_detect_stmt_type 会误判 income）。
    income 缺失的行保留 indicator 字段（revenue/net_profit 为空不阻塞）。
    """
    frames = []
    for period in periods:
        try:
            ind = await fetch_financial_indicator_by_period(conn, period)
        except DataNotFoundError:
            logger.warning(f"报告期 {period} fina_indicator 无数据，跳过")
            continue
        if ind is None:
            return None  # 接口不存在/源不可用
        try:
            inc = await fetch_income_by_period(conn, period)
        except DataNotFoundError:
            inc = None
            logger.warning(f"报告期 {period} income 无数据，仅用 indicator 字段")
        ind = _merge_period_financials(ind, inc, period)
        frames.append(ind)
        logger.info(f"报告期 {period} 财务批量: {len(ind)} 行")
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)
