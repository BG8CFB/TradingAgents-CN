"""Alpha Vantage US Provider — 25/天免费层，仅兜底。"""

import asyncio
import logging

import pandas as pd

from app.data.sources.base.provider import BaseProvider
from app.utils.ds_key_utils import get_datasource_api_key

logger = logging.getLogger(__name__)

AV_BASE_URL = "https://www.alphavantage.co/query"


class AlphaVantageUSProvider(BaseProvider):
    """Alpha Vantage 美股数据源 Provider。"""

    def __init__(self):
        super().__init__(name="alpha_vantage", market="US")

    async def connect(self) -> bool:
        self.connected = True
        return True

    def is_available(self) -> bool:
        return bool(get_datasource_api_key("alpha_vantage") or "")

    async def get_daily_quotes(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        api_key = get_datasource_api_key("alpha_vantage") or ""
        if not api_key:
            return None
        try:
            import urllib.request
            import json

            url = f"{AV_BASE_URL}?function=TIME_SERIES_DAILY&symbol={symbol.upper()}&outputsize=full&apikey={api_key}"

            def _fetch():
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                ts = data.get("Time Series (Daily)")
                if not ts:
                    return None
                records = []
                for date_str, values in ts.items():
                    if start_date <= date_str <= end_date:
                        records.append({
                            "trade_date": date_str,
                            "open": values.get("1. open"),
                            "high": values.get("2. high"),
                            "low": values.get("3. low"),
                            "close": values.get("4. close"),
                            "volume": values.get("5. volume"),
                            "symbol": symbol.upper(),
                        })
                return pd.DataFrame(records) if records else None

            return await asyncio.to_thread(_fetch)
        except Exception as e:
            logger.debug(f"Alpha Vantage 行情失败 {symbol}: {e}")
            return None

    async def get_financial_data(
        self, symbol: str, start_date: str, end_date: str,
        statement_type: str = "", **kwargs
    ) -> pd.DataFrame:
        api_key = get_datasource_api_key("alpha_vantage") or ""
        if not api_key:
            return None
        try:
            import urllib.request
            import json

            func_map = {
                "income": "INCOME_STATEMENT",
                "balance": "BALANCE_SHEET",
                "cashflow": "CASH_FLOW",
            }
            func = func_map.get(statement_type, "INCOME_STATEMENT")
            url = f"{AV_BASE_URL}?function={func}&symbol={symbol.upper()}&apikey={api_key}"

            def _fetch():
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                reports = data.get("annualReports") or data.get("quarterlyReports") or []
                if not reports:
                    return None
                for r in reports:
                    r["symbol"] = symbol.upper()
                return pd.DataFrame(reports)

            return await asyncio.to_thread(_fetch)
        except Exception as e:
            logger.debug(f"Alpha Vantage 财务失败 {symbol}: {e}")
            return None

    async def get_corporate_actions(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        api_key = get_datasource_api_key("alpha_vantage") or ""
        if not api_key:
            return None
        try:
            import urllib.request
            import json

            url = f"{AV_BASE_URL}?function=DIVIDENDS&symbol={symbol.upper()}&apikey={api_key}"

            def _fetch():
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                divs = data.get("data", [])
                records = []
                for d in divs:
                    ex_date = d.get("ex_dividend_date", "")
                    if start_date <= ex_date <= end_date:
                        records.append({
                            "date": ex_date,
                            "action_type": "cash_dividend",
                            "amount": d.get("amount"),
                            "symbol": symbol.upper(),
                        })
                return pd.DataFrame(records) if records else None

            return await asyncio.to_thread(_fetch)
        except Exception as e:
            logger.debug(f"Alpha Vantage 公司行为失败 {symbol}: {e}")
            return None
