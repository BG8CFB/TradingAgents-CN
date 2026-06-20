"""
Tushare US 美股交易日历 API
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

from app.data.sources.base.exceptions import DataNotFoundError, DataSourceUnavailableError
from app.data.sources.base.mappers import (
    is_empty_result,
    map_network_exception,
    map_tushare_code,
)

logger = logging.getLogger(__name__)

_DOMAIN = "trade_calendar"


async def fetch_trade_calendar(
    api,
    exchange: str = "NYSE",
    start_date: str = None,
    end_date: str = None,
) -> Optional[pd.DataFrame]:
    """获取美股交易日历。

    Args:
        api: tushare pro_api 实例
        exchange: 交易所代码，如 NYSE, NASDAQ
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)

    Returns:
        交易日历 DataFrame，失败返回 None
    """
    if api is None:
        return None
    params: dict = {"exchange": exchange}
    if start_date:
        params["start_date"] = start_date.replace("-", "")
    if end_date:
        params["end_date"] = end_date.replace("-", "")
    try:
        df = await asyncio.to_thread(api.us_tradecal, **params)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "tushare_us", _DOMAIN)
    except Exception as exc:
        error_code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
        mapped = map_tushare_code(error_code, "tushare_us", _DOMAIN, str(exc))
        if mapped is not None:
            raise mapped
        raise DataSourceUnavailableError(
            "tushare_us", _DOMAIN, f"exchange={exchange}: {exc}"
        )

    if is_empty_result(df):
        logger.warning(f"Tushare US 交易日历返回空数据: {exchange}")
        raise DataNotFoundError("tushare_us", _DOMAIN, f"{exchange} 无数据")

    logger.info(f"Tushare US 交易日历: {exchange} {len(df)} 条")
    return df
