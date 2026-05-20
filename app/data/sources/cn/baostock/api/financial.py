"""
BaoStock 财务数据 API（5 个子查询）
"""
import asyncio
import logging
from typing import Any, Dict, Optional

import pandas as pd

from .connection import baostock_session
from .daily_quotes import _to_baostock_code

logger = logging.getLogger(__name__)


async def fetch_financial_data(code: str, year: int = None, quarter: int = None) -> Optional[Dict[str, Any]]:
    """获取多维度财务数据"""
    try:
        bs_code = _to_baostock_code(code)
        async with baostock_session():
            result: Dict[str, Any] = {"symbol": code, "data_source": "baostock"}

            queries = [
                ("profit", _query_profit),
                ("operation", _query_operation),
                ("growth", _query_growth),
                ("balance", _query_balance),
                ("cashflow", _query_cashflow),
            ]

            for name, fn in queries:
                try:
                    df = await asyncio.to_thread(fn, bs_code, year, quarter)
                    if df is not None and not df.empty:
                        result[name] = df.iloc[0].to_dict() if len(df) == 1 else df.to_dict("records")
                except Exception:
                    continue

            return result if len(result) > 2 else None

    except Exception as e:
        logger.error(f"BaoStock 获取财务数据失败 {code}: {e}")
        return None


def _query_profit(code, year, quarter):
    return _run_query(bs.query_profit_data, code, year, quarter)


def _query_operation(code, year, quarter):
    return _run_query(bs.query_operation_data, code, year, quarter)


def _query_growth(code, year, quarter):
    return _run_query(bs.query_growth_data, code, year, quarter)


def _query_balance(code, year, quarter):
    return _run_query(bs.query_balance_data, code, year, quarter)


def _query_cashflow(code, year, quarter):
    return _run_query(bs.query_cash_flow_data, code, year, quarter)


def _run_query(query_fn, code, year, quarter):
    import datetime
    if year is None:
        year = datetime.datetime.now().year
    if quarter is None:
        quarter = max(1, (datetime.datetime.now().month - 1) // 3)

    rs = query_fn(code=code, year=year, quarter=quarter)
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    if rows:
        return pd.DataFrame(rows, columns=rs.fields)
    return None
