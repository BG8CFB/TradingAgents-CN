"""
AKShare 财务数据 API
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


def _safe_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        if isinstance(value, str):
            value = value.strip()
            if not value or value.lower() in ("nan", "null", "none", "--", "-"):
                return None
            value = value.replace(",", "").replace("万", "").replace("亿", "")
        if isinstance(value, float) and value != value:
            return None
        return float(value)
    except (ValueError, TypeError, AttributeError):
        return None


def _extract_report_period(raw_row: Dict) -> Optional[str]:
    """从多种可能的字段中提取报告期。"""
    for key in ("报告期", "end_date", "ANN_DATE", "report_date"):
        v = raw_row.get(key)
        if v:
            return str(v)
    return None


def _build_financial_row(code: str, tables: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
    """从多张财务报表合并出一行标准化记录。"""
    # 各表取最新一期（第一行）
    abstract_row = tables.get("abstract")
    balance_row = tables.get("balance")
    income_row = tables.get("income")
    cashflow_row = tables.get("cashflow")

    a = abstract_row.iloc[0].to_dict() if abstract_row is not None and not abstract_row.empty else {}
    b = balance_row.iloc[0].to_dict() if balance_row is not None and not balance_row.empty else {}
    i = income_row.iloc[0].to_dict() if income_row is not None and not income_row.empty else {}
    c = cashflow_row.iloc[0].to_dict() if cashflow_row is not None and not cashflow_row.empty else {}

    report_period = _extract_report_period(a) or _extract_report_period(b) or _extract_report_period(i)

    # 收入 / 利润 — 优先从 abstract（摘要）提取，再从 income（利润表）提取
    revenue = _safe_float(
        a.get("营业收入") or a.get("revenue")
        or i.get("营业收入") or i.get("revenue") or i.get("total_revenue")
    )
    net_profit = _safe_float(
        a.get("净利润") or a.get("net_profit")
        or i.get("净利润") or i.get("net_profit") or i.get("n_income_attr_p")
    )
    total_assets = _safe_float(b.get("总资产") or b.get("total_assets"))
    total_equity = _safe_float(
        b.get("所有者权益合计") or b.get("total_equity")
        or b.get("total_hldr_eqy_exc_min_int")
    )
    total_liab = _safe_float(b.get("总负债") or b.get("total_liab"))
    roe = _safe_float(a.get("净资产收益率") or a.get("roe"))
    gross_margin = _safe_float(a.get("毛利率") or a.get("grossprofit_margin") or a.get("gross_margin"))
    net_margin = _safe_float(a.get("净利率") or a.get("netprofit_margin") or a.get("net_margin"))
    eps = _safe_float(a.get("每股收益") or a.get("基本每股收益") or a.get("eps"))
    bps = _safe_float(a.get("每股净资产") or a.get("bps"))
    operating_cashflow = _safe_float(
        c.get("经营活动产生的现金流量净额") or c.get("n_cashflow_act")
    )
    revenue_ttm = _safe_float(a.get("营业收入TTM") or a.get("revenue_ttm"))
    net_profit_ttm = _safe_float(a.get("净利润TTM") or a.get("net_profit_ttm"))

    return {
        "symbol": code,
        "report_period": report_period,
        "report_date": report_period,
        "data_source": "akshare",
        "revenue": revenue,
        "revenue_ttm": revenue_ttm,
        "net_profit": net_profit,
        "net_profit_ttm": net_profit_ttm,
        "total_assets": total_assets,
        "total_equity": total_equity,
        "total_liab": total_liab,
        "roe": roe,
        "gross_margin": gross_margin,
        "net_margin": net_margin,
        "eps": eps,
        "bps": bps,
        "operating_cashflow": operating_cashflow,
    }


async def fetch_financial_data(code: str) -> Optional[pd.DataFrame]:
    """获取多表联合财务数据，返回 DataFrame（一行或多行）。"""
    try:
        import akshare as ak

        tables: Dict[str, Optional[pd.DataFrame]] = {}

        fetch_tasks = [
            ("abstract", lambda: ak.stock_financial_abstract_ths(symbol=code, indicator="按年度")),
            ("balance", lambda: ak.stock_balance_sheet_by_report_em(symbol=code)),
            ("income", lambda: ak.stock_profit_sheet_by_report_em(symbol=code)),
            ("cashflow", lambda: ak.stock_cash_flow_sheet_by_report_em(symbol=code)),
        ]

        for name, fn in fetch_tasks:
            try:
                df = await asyncio.to_thread(fn)
                if df is not None and not df.empty:
                    tables[name] = df
            except Exception:
                continue

        if not tables:
            return None

        row = _build_financial_row(code, tables)
        return pd.DataFrame([row])

    except Exception as e:
        logger.error(f"AKShare 获取财务数据失败 {code}: {e}")
        return None
