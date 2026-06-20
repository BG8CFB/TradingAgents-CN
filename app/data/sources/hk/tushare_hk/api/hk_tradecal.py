"""
Tushare HK 港股交易日历 API — hk_tradecal 接口封装。
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


def _format_compact(date_str: str) -> str:
    """YYYY-MM-DD -> YYYYMMDD"""
    return str(date_str).replace("-", "") if date_str else ""


async def fetch_trade_calendar(
    api,
    exchange: str = "HKEX",
    start_date: str = None,
    end_date: str = None,
) -> Optional[pd.DataFrame]:
    """获取港股交易日历。

    Parameters
    ----------
    api : tushare.pro_api
        已初始化的 Tushare pro_api 实例。
    exchange : str
        交易所代码，默认 HKEX。
    start_date : str
        起始日期，格式 YYYY-MM-DD 或 YYYYMMDD。
    end_date : str
        截止日期，格式 YYYY-MM-DD 或 YYYYMMDD。

    Returns
    -------
    Optional[pd.DataFrame]
        原始 DataFrame，包含 exchange / cal_date / is_open 等字段。
    """
    if api is None:
        return None
    params: dict = {"exchange": exchange}
    if start_date:
        params["start_date"] = _format_compact(start_date)
    if end_date:
        params["end_date"] = _format_compact(end_date)
    try:
        df = await asyncio.to_thread(lambda: api.hk_tradecal(**params))
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "tushare_hk", _DOMAIN)
    except Exception as exc:
        error_code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
        mapped = map_tushare_code(error_code, "tushare_hk", _DOMAIN, str(exc))
        if mapped is not None:
            raise mapped
        raise DataSourceUnavailableError(
            "tushare_hk", _DOMAIN, f"exchange={exchange}: {exc}"
        )

    if is_empty_result(df):
        logger.warning(f"Tushare HK 交易日历返回空数据: {exchange}")
        raise DataNotFoundError("tushare_hk", _DOMAIN, f"{exchange} 无数据")

    logger.info(f"Tushare HK 交易日历: {exchange} {len(df)} 条")
    return df
