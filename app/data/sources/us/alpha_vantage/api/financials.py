"""
Alpha Vantage US 美股财务数据 API
"""
import asyncio
import json
import logging
import os
import urllib.request
from typing import Optional

from app.core.env import get_env

import pandas as pd

logger = logging.getLogger(__name__)

_AV_BASE_URL = "https://www.alphavantage.co/query"


async def fetch_financials(
    symbol: str,
    statement_type: str = "income",
) -> Optional[pd.DataFrame]:
    """获取美股财务报表数据。

    通过 Alpha Vantage INCOME_STATEMENT/BALANCE_SHEET/CASH_FLOW 端点获取。
    优先使用年报数据 (annualReports)，如无则使用季报 (quarterlyReports)。

    Args:
        symbol: 股票代码（大写），如 "AAPL"
        statement_type: 报表类型 ("income"/"balance"/"cashflow")

    Returns:
        财务数据 DataFrame，失败返回 None
    """
    api_key = get_env("ALPHA_VANTAGE_API_KEY", "")
    if not api_key:
        logger.debug("Alpha Vantage API Key 未配置")
        return None
    try:
        ticker = symbol.upper().strip()

        func_map = {
            "income": "INCOME_STATEMENT",
            "balance": "BALANCE_SHEET",
            "cashflow": "CASH_FLOW",
        }
        func = func_map.get(statement_type, "INCOME_STATEMENT")
        url = f"{_AV_BASE_URL}?function={func}&symbol={ticker}&apikey={api_key}"

        def _fetch():
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            reports = data.get("annualReports") or data.get("quarterlyReports") or []
            if not reports:
                return None
            for r in reports:
                r["symbol"] = ticker
            return pd.DataFrame(reports)

        df = await asyncio.to_thread(_fetch)
        if df is not None and not df.empty:
            logger.info(
                f"Alpha Vantage 财务数据 ({statement_type}): {ticker} {len(df)} 条"
            )
        return df
    except Exception as e:
        logger.debug(f"Alpha Vantage 获取财务数据失败 {symbol} ({statement_type}): {e}")
        return None
