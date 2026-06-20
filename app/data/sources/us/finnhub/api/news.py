"""
Finnhub US 美股新闻 API
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

_DOMAIN = "news"


async def fetch_news(
    symbol: str,
    start_date: str,
    end_date: str,
) -> Optional[pd.DataFrame]:
    """获取美股公司新闻。

    通过 finnhub.Client.company_news(symbol, _from, to) 获取。
    最多返回 50 条新闻。

    Args:
        symbol: 股票代码（大写），如 "AAPL"
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)

    Returns:
        新闻 DataFrame，失败返回 None

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
            news = client.company_news(ticker, _from=start_date, to=end_date)
            return pd.DataFrame(news[:50]) if news else None

        try:
            # 公司新闻按日期范围查询，给 15s 超时
            df = await asyncio.wait_for(asyncio.to_thread(_fetch), timeout=15)
        except asyncio.TimeoutError as exc:
            raise NetworkError("finnhub", _DOMAIN, f"symbol={symbol}: 新闻拉取超时（>15s）") from exc
        except finnhub.FinnhubAPIException as exc:
            # 基于 HTTP 状态码分类（429→RateLimitedError，401/403→TokenInvalidError，5xx→DataSourceUnavailableError）
            status = getattr(exc, "status_code", None) or 0
            raise map_http_status_to_error(
                status, "finnhub", _DOMAIN, f"symbol={symbol}: {exc}"
            ) from exc
    except DataSourceError:
        # 已分类异常透传，避免被外层 Exception 重新包装
        raise
    except (ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "finnhub", _DOMAIN)
    except (KeyError, ValueError, TypeError) as exc:
        raise DataFormatError("finnhub", _DOMAIN, f"symbol={symbol}: {exc}")
    except Exception as exc:
        raise DataSourceUnavailableError("finnhub", _DOMAIN, f"symbol={symbol}: {exc}")

    if is_empty_result(df):
        logger.warning(f"Finnhub 返回空数据: {symbol} 新闻")
        raise DataNotFoundError("finnhub", _DOMAIN, f"{symbol} 无新闻数据")

    logger.info(f"Finnhub 获取成功: {symbol} {len(df) if df is not None else 0} 条")
    return df
