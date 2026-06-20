"""
AKShare 财务数据 API
"""
import asyncio
import logging
from typing import Any, Dict, Optional

import pandas as pd
import pandas.errors

from app.data.sources.base.exceptions import (
    DataFormatError,
    DataNotFoundError,
    DataSourceUnavailableError,
)
from app.data.sources.base.mappers import map_network_exception

logger = logging.getLogger(__name__)

_DOMAIN = "financial"


def _safe_float(value) -> Optional[float]:
    """安全转 float，支持中文单位（亿/万）和百分号换算。

    示例：
    - "3.5亿"   → 3.5e8
    - "12.5%"   → 0.125
    - "1,234.5" → 1234.5
    - None / NaN / "--" / "-" → None
    """
    if value is None:
        return None
    try:
        if isinstance(value, str):
            value = value.strip()
            if not value or value.lower() in ("nan", "null", "none", "--", "-"):
                return None
            value = value.replace(",", "")
            multiplier = 1.0
            # 优先匹配百分号（无单位前缀），其次匹配亿/万单位
            if value.endswith("%"):
                return float(value[:-1]) / 100.0
            if value.endswith("亿"):
                multiplier = 1e8
                value = value[:-1]
            elif value.endswith("万"):
                multiplier = 1e4
                value = value[:-1]
        if isinstance(value, float) and value != value:
            return None
        return float(value) * multiplier
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


async def fetch_financial_data(
    code: str,
    start_date: str = None,
    end_date: str = None,
) -> pd.DataFrame:
    """获取多表联合财务数据，返回 DataFrame（一行或多行）。

    日期过滤：AKShare 财务接口不支持服务端日期范围查询，拉取全量后在内存中
    按报告期列（REPORT_DATE / 报告期）过滤，减少返回调用方范围外的冗余数据。

    Raises:
        NetworkError: 网络/超时异常（可重试）
        DataFormatError: AKShare 返回结构异常（不可重试）
        DataNotFoundError: 所有财务子表均无数据（不可重试）
        DataSourceUnavailableError: 其他未知异常
    """
    try:
        import akshare as ak

        tables: Dict[str, Optional[pd.DataFrame]] = {}

        from app.data.sources.cn.akshare.api.anti_scraping import wait_rate_limit

        fetch_tasks = [
            ("abstract", lambda: (wait_rate_limit(), ak.stock_financial_abstract_ths(symbol=code, indicator="按年度"))[1]),
            ("balance", lambda: (wait_rate_limit(), ak.stock_balance_sheet_by_report_em(symbol=code))[1]),
            ("income", lambda: (wait_rate_limit(), ak.stock_profit_sheet_by_report_em(symbol=code))[1]),
            ("cashflow", lambda: (wait_rate_limit(), ak.stock_cash_flow_sheet_by_report_em(symbol=code))[1]),
        ]

        for name, fn in fetch_tasks:
            try:
                df = await asyncio.to_thread(fn)
                if df is not None and not df.empty:
                    if start_date or end_date:
                        df = _filter_df_by_report_period(df, start_date, end_date)
                    if df is not None and not df.empty:
                        tables[name] = df
            except (
                KeyError,
                IndexError,
                AttributeError,
                ValueError,
                pandas.errors.EmptyDataError,
            ) as e:
                # 单个子表数据格式异常（AKShare 返回结构变化或缺字段）：跳过该表，不影响其他表
                logger.debug(f"AKShare获取财务数据 {name} 格式异常: {e}")
                continue
            # 其他异常（网络/超时/未知）不在此处吞掉，让其上抛到外层异常分类器处理

    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        # 网络异常：可重试
        raise map_network_exception(exc, "akshare", _DOMAIN)
    except (KeyError, IndexError, AttributeError, ValueError) as exc:
        # 数据格式异常：AKShare 返回结构不符合预期，不可重试
        raise DataFormatError("akshare", _DOMAIN, f"code={code}: {exc}")
    except Exception as exc:
        # 其他未知异常
        raise DataSourceUnavailableError("akshare", _DOMAIN, f"code={code}: {exc}")

    # 所有子表均无数据 → 视为业务空结果
    if not tables:
        raise DataNotFoundError("akshare", _DOMAIN, f"code={code} 所有财务子表均无数据")

    row = _build_financial_row(code, tables)
    return pd.DataFrame([row])


def _filter_df_by_report_period(
    df: "pd.DataFrame", start_date: str, end_date: str
) -> "pd.DataFrame":
    """按报告期列过滤 AKShare 财务 DataFrame。

    AKShare 各财务报表的报告期列名不统一（REPORT_DATE / 报告期 / 报表日期等），
    这里尝试常见列名。日期统一去掉分隔符后做字符串比较。
    返回过滤后的 DataFrame；若无匹配列则原样返回（不阻塞业务）。
    """
    period_cols = ["REPORT_DATE", "报告期", "报表日期", "报告日", "ANN_DATE"]
    col = None
    for c in period_cols:
        if c in df.columns:
            col = c
            break
    if col is None:
        return df

    start = str(start_date).replace("-", "") if start_date else None
    end = str(end_date).replace("-", "") if end_date else None

    def _norm(v):
        return str(v).replace("-", "") if v is not None else ""

    mask = df[col].apply(_norm)
    if start:
        mask = mask & df[col].apply(lambda v: _norm(v) >= start)
    if end:
        mask = mask & df[col].apply(lambda v: _norm(v) <= end)
    return df[mask]
