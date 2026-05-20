"""
AKShare 财务数据 API
"""
import asyncio
import logging
from typing import Any, Dict, Optional

import pandas as pd

logger = logging.getLogger(__name__)


async def fetch_financial_data(code: str) -> Optional[Dict[str, Any]]:
    """获取多表联合财务数据"""
    try:
        import akshare as ak

        financial_data = {}

        tables = [
            ("abstract", lambda: ak.stock_financial_abstract_ths(symbol=code, indicator="按年度")),
            ("balance", lambda: ak.stock_balance_sheet_by_report_em(symbol=code)),
            ("income", lambda: ak.stock_profit_sheet_by_report_em(symbol=code)),
            ("cashflow", lambda: ak.stock_cash_flow_sheet_by_report_em(symbol=code)),
        ]

        for name, fn in tables:
            try:
                df = await asyncio.to_thread(fn)
                if df is not None and not df.empty:
                    financial_data[name] = df
            except Exception:
                continue

        if not financial_data:
            return None

        # 取各表第一条（最新一期）
        result = {"symbol": code, "data_source": "akshare"}
        for name, df in financial_data.items():
            if isinstance(df, pd.DataFrame) and not df.empty:
                result[name] = df.iloc[0].to_dict()

        return result

    except Exception as e:
        logger.error(f"AKShare 获取财务数据失败 {code}: {e}")
        return None
