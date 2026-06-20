"""
Alpha Vantage US 美股财务数据 API
"""
import asyncio
import json
import logging
import urllib.request
from typing import Optional

from app.utils.ds_key_utils import get_datasource_api_key

import pandas as pd

from app.data.sources.base.exceptions import (
    DataNotFoundError,
    DataSourceUnavailableError,
)
from app.data.sources.base.mappers import (
    is_empty_result,
    map_network_exception,
)

logger = logging.getLogger(__name__)

_DOMAIN = "financials"

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

    Raises:
        NetworkError: 网络/超时异常（可重试）
        DataFormatError: Alpha Vantage 返回结构异常（不可重试）
        DataNotFoundError: 返回空数据（不可重试）
        DataSourceUnavailableError: 其他未知异常
    """
    api_key = get_datasource_api_key("alpha_vantage") or ""
    if not api_key:
        logger.debug("Alpha Vantage API Key 未配置")
        return None

    ticker = symbol.upper().strip()

    func_map = {
        "income": "INCOME_STATEMENT",
        "balance": "BALANCE_SHEET",
        "cashflow": "CASH_FLOW",
    }
    func = func_map.get(statement_type, "INCOME_STATEMENT")
    url = f"{_AV_BASE_URL}?function={func}&symbol={ticker}&apikey={api_key}"

    try:

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
    except (asyncio.TimeoutError, ConnectionError, TimeoutError, urllib.error.URLError) as exc:
        raise map_network_exception(exc, "alpha_vantage", _DOMAIN)
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        from app.data.sources.base.exceptions import DataFormatError
        raise DataFormatError("alpha_vantage", _DOMAIN, f"symbol={symbol}: {exc}")
    except Exception as exc:
        raise DataSourceUnavailableError("alpha_vantage", _DOMAIN, f"symbol={symbol}: {exc}")

    if is_empty_result(df):
        logger.warning(f"Alpha Vantage 返回空数据: {symbol} ({statement_type})")
        raise DataNotFoundError("alpha_vantage", _DOMAIN, f"{symbol} ({statement_type}) 无数据")

    logger.info(
        f"Alpha Vantage 获取成功 ({statement_type}): {symbol} {len(df) if df is not None else 0} 条"
    )
    return df
