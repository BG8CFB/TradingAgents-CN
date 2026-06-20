"""
Finnhub US 美股实时行情快照 API
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

from app.utils.ds_key_utils import get_datasource_api_key

from app.data.sources.base.exceptions import (
    DataFormatError,
    DataNotFoundError,
    DataSourceError,
    DataSourceUnavailableError,
    NetworkError,
)
from app.data.sources.base.mappers import (
    is_empty_result,
    map_http_status_to_error,
    map_network_exception,
)

logger = logging.getLogger(__name__)

_DOMAIN = "market_quotes"


async def fetch_quote(symbol: str) -> Optional[pd.DataFrame]:
    """获取美股实时行情快照。

    通过 finnhub.Client.quote(symbol) 获取，包装为 DataFrame。

    Args:
        symbol: 股票代码（大写），如 "AAPL"

    Returns:
        行情快照 DataFrame（单行），失败返回 None

    Raises:
        NetworkError: 网络/超时异常（可重试）
        DataFormatError: Finnhub 返回结构异常（不可重试）
        DataNotFoundError: 返回空数据（不可重试）
        DataSourceUnavailableError: 其他未知异常
    """
    api_key = get_datasource_api_key("finnhub") or ""
    if not api_key:
        logger.debug("Finnhub API Key 未配置")
        return None

    ticker = symbol.upper().strip()

    try:
        import finnhub

        def _fetch():
            client = finnhub.Client(api_key=api_key)
            quote = client.quote(ticker)
            return quote if quote and "c" in quote else None

        try:
            # 实时行情快照：5s 超时；finnhub.Client 默认无显式超时，必须外层包裹
            quote = await asyncio.wait_for(asyncio.to_thread(_fetch), timeout=5)
        except asyncio.TimeoutError as exc:
            raise NetworkError("finnhub", _DOMAIN, f"symbol={symbol}: timeout after 5s") from exc
        except finnhub.FinnhubAPIException as exc:
            # 基于 HTTP 状态码分类（429→RateLimitedError，401/403→TokenInvalidError，5xx→DataSourceUnavailableError）
            status = getattr(exc, "status_code", None) or 0
            raise map_http_status_to_error(
                status, "finnhub", _DOMAIN, f"symbol={symbol}: {exc}"
            ) from exc
    except DataSourceError:
        # 已分类异常（RateLimitedError/TokenInvalidError/DataFormatError 等）直接透传，
        # 不能被外层 Exception 包装成 DataSourceUnavailableError 丢失语义
        raise
    except (ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "finnhub", _DOMAIN)
    except (KeyError, ValueError, TypeError) as exc:
        raise DataFormatError("finnhub", _DOMAIN, f"symbol={symbol}: {exc}")
    except Exception as exc:
        raise DataSourceUnavailableError("finnhub", _DOMAIN, f"symbol={symbol}: {exc}")

    # quote 为 dict，使用 is_empty_result 检测 None/空 dict
    if is_empty_result(quote) or not quote:
        logger.warning(f"Finnhub 返回空数据: {symbol}")
        raise DataNotFoundError("finnhub", _DOMAIN, f"{symbol} 无数据")

    df = pd.DataFrame([{
        "symbol": ticker,
        "price": quote.get("c"),
        "change": quote.get("d"),
        "pct_change": quote.get("dp"),
        "volume": quote.get("v"),
        "high": quote.get("h"),
        "low": quote.get("l"),
        "open": quote.get("o"),
        "previous_close": quote.get("pc"),
    }])
    logger.info(f"Finnhub 获取成功: {symbol}")
    return df
