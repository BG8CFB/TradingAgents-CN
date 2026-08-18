"""Alpha Vantage US Provider — 25/天免费层，仅兜底。"""

import asyncio
import logging

import pandas as pd

from app.data.sources.base.provider import BaseProvider
from app.utils.ds_key_utils import get_datasource_api_key

logger = logging.getLogger(__name__)

AV_BASE_URL = "https://www.alphavantage.co/query"


def _redact_apikey(text: str) -> str:
    """脱敏文本中的 apikey 参数，防止异常 traceback 泄漏 API Key 到日志。"""
    import re

    return re.sub(r"apikey=[^&\"\s]+", "apikey=REDACTED", text)


def _safe_urlopen(url: str, timeout: int = 30):
    """封装 urlopen，捕获 HTTPError 并对含 apikey 的 URL 脱敏后重新抛出。

    urllib.error.HTTPError 的 filename 属性保存请求 URL（含明文 apikey），
    若不处理，异常 traceback / 代理日志会泄漏 API Key。
    """
    import urllib.request
    import urllib.error

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        # HTTPError.filename 存储完整请求 URL（含 apikey），脱敏后重新抛出
        raise Exception(_redact_apikey(str(exc))) from None


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
            import json

            url = f"{AV_BASE_URL}?function=TIME_SERIES_DAILY&symbol={symbol.upper()}&outputsize=full&apikey={api_key}"

            def _fetch():
                with _safe_urlopen(url, timeout=30) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                ts = data.get("Time Series (Daily)")
                if not ts:
                    return None
                records = []
                for date_str, values in ts.items():
                    if start_date <= date_str <= end_date:
                        records.append(
                            {
                                "trade_date": date_str,
                                "open": values.get("1. open"),
                                "high": values.get("2. high"),
                                "low": values.get("3. low"),
                                "close": values.get("4. close"),
                                "volume": values.get("5. volume"),
                                "symbol": symbol.upper(),
                            }
                        )
                return pd.DataFrame(records) if records else None

            return await asyncio.to_thread(_fetch)
        except Exception as e:
            logger.warning(f"Alpha Vantage 行情失败 {symbol}: {_redact_apikey(str(e))}")
            return None

    async def get_financial_data(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        statement_type: str = "",
        **kwargs,
    ) -> pd.DataFrame:
        api_key = get_datasource_api_key("alpha_vantage") or ""
        if not api_key:
            return None
        try:
            import json

            func_map = {
                "income": "INCOME_STATEMENT",
                "balance": "BALANCE_SHEET",
                "cashflow": "CASH_FLOW",
            }
            func = func_map.get(statement_type, "INCOME_STATEMENT")
            url = f"{AV_BASE_URL}?function={func}&symbol={symbol.upper()}&apikey={api_key}"

            def _fetch():
                with _safe_urlopen(url, timeout=30) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                reports = (
                    data.get("annualReports") or data.get("quarterlyReports") or []
                )
                if not reports:
                    return None
                for r in reports:
                    r["symbol"] = symbol.upper()
                return pd.DataFrame(reports)

            return await asyncio.to_thread(_fetch)
        except Exception as e:
            logger.warning(f"Alpha Vantage 财务失败 {symbol}: {_redact_apikey(str(e))}")
            return None

    async def get_corporate_actions(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        api_key = get_datasource_api_key("alpha_vantage") or ""
        if not api_key:
            return None
        try:
            import json

            url = f"{AV_BASE_URL}?function=DIVIDENDS&symbol={symbol.upper()}&apikey={api_key}"

            def _fetch():
                with _safe_urlopen(url, timeout=30) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                divs = data.get("data", [])
                records = []
                for d in divs:
                    ex_date = d.get("ex_dividend_date", "")
                    if start_date <= ex_date <= end_date:
                        records.append(
                            {
                                "date": ex_date,
                                "action_type": "cash_dividend",
                                "amount": d.get("amount"),
                                "symbol": symbol.upper(),
                            }
                        )
                return pd.DataFrame(records) if records else None

            return await asyncio.to_thread(_fetch)
        except Exception as e:
            logger.warning(
                f"Alpha Vantage 公司行为失败 {symbol}: {_redact_apikey(str(e))}"
            )
            return None
