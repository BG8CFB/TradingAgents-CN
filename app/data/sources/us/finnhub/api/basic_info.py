"""
Finnhub US 美股基础信息 API（股票列表）
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

_DOMAIN = "basic_info"


async def fetch_stock_list() -> Optional[pd.DataFrame]:
    """获取美股股票列表。

    通过 finnhub.Client.stock_symbols(exchange="US") 获取全市场股票列表。

    Returns:
        股票列表 DataFrame，失败返回 None

    Raises:
        NetworkError: 网络/超时异常（可重试）
        DataFormatError: Finnhub 返回结构异常（不可重试）
        DataNotFoundError: 返回空数据（不可重试）
        DataSourceUnavailableError: 其他未知异常
    """
    api_key = get_datasource_api_key("finnhub")
    if not api_key:
        logger.debug("Finnhub API Key 未配置")
        return None

    try:
        import finnhub

        def _fetch():
            client = finnhub.Client(api_key=api_key)
            symbols = client.stock_symbols(exchange="US")
            return pd.DataFrame(symbols) if symbols else None

        try:
            # 股票列表是一次性全市场拉取，数据量较大，给 15s 超时
            df = await asyncio.wait_for(asyncio.to_thread(_fetch), timeout=15)
        except asyncio.TimeoutError as exc:
            raise NetworkError("finnhub", _DOMAIN, "股票列表拉取超时（>15s）") from exc
        except finnhub.FinnhubAPIException as exc:
            # 基于 HTTP 状态码分类（429→RateLimitedError，401/403→TokenInvalidError，5xx→DataSourceUnavailableError）
            status = getattr(exc, "status_code", None) or 0
            raise map_http_status_to_error(
                status, "finnhub", _DOMAIN, str(exc) or "FinnhubAPIException"
            ) from exc
    except DataSourceError:
        # 已分类异常透传，避免被外层 Exception 重新包装
        raise
    except (ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "finnhub", _DOMAIN)
    except (KeyError, ValueError, TypeError) as exc:
        raise DataFormatError("finnhub", _DOMAIN, str(exc))
    except Exception as exc:
        raise DataSourceUnavailableError("finnhub", _DOMAIN, str(exc))

    if is_empty_result(df):
        logger.warning("Finnhub 返回空数据: 股票列表")
        raise DataNotFoundError("finnhub", _DOMAIN, "股票列表无数据")

    logger.info(f"Finnhub 获取成功: 股票列表 {len(df) if df is not None else 0} 只")
    return df
