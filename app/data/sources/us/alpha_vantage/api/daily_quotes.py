"""
Alpha Vantage US 美股日线行情 API
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

_DOMAIN = "daily_quotes"

_AV_BASE_URL = "https://www.alphavantage.co/query"


async def fetch_daily_quotes(
    symbol: str,
    start_date: str,
    end_date: str,
) -> Optional[pd.DataFrame]:
    """获取美股日线行情。

    通过 Alpha Vantage TIME_SERIES_DAILY 端点获取全量日线数据，
    再按日期范围过滤。

    Args:
        symbol: 股票代码（大写），如 "AAPL"
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)

    Returns:
        日线行情 DataFrame，失败返回 None

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
    url = (
        f"{_AV_BASE_URL}?function=TIME_SERIES_DAILY"
        f"&symbol={ticker}&outputsize=full&apikey={api_key}"
    )

    try:

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
                        "symbol": ticker,
                    })
            return pd.DataFrame(records) if records else None

        df = await asyncio.to_thread(_fetch)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError, urllib.error.URLError) as exc:
        raise map_network_exception(exc, "alpha_vantage", _DOMAIN)
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        from app.data.sources.base.exceptions import DataFormatError
        raise DataFormatError("alpha_vantage", _DOMAIN, f"symbol={symbol}: {exc}")
    except Exception as exc:
        raise DataSourceUnavailableError("alpha_vantage", _DOMAIN, f"symbol={symbol}: {exc}")

    if is_empty_result(df):
        logger.warning(f"Alpha Vantage 返回空数据: {symbol}")
        raise DataNotFoundError("alpha_vantage", _DOMAIN, f"{symbol} 无数据")

    logger.info(f"Alpha Vantage 获取成功: {symbol} {len(df) if df is not None else 0} 条")
    return df
