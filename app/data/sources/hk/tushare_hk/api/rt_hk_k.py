"""
Tushare HK 港股实时行情 API — rt_hk_k 接口封装。
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

_DOMAIN = "realtime_quotes"


async def fetch_realtime_quotes(api) -> Optional[pd.DataFrame]:
    """获取港股全市场实时行情快照。

    Parameters
    ----------
    api : tushare.pro_api
        已初始化的 Tushare pro_api 实例。

    Returns
    -------
    Optional[pd.DataFrame]
        原始 DataFrame，包含 ts_code / price / volume / amount 等字段。
    """
    if api is None:
        return None
    try:
        df = await asyncio.to_thread(lambda: api.rt_hk_k())
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "tushare_hk", _DOMAIN)
    except Exception as exc:
        error_code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
        mapped = map_tushare_code(error_code, "tushare_hk", _DOMAIN, str(exc))
        if mapped is not None:
            raise mapped
        raise DataSourceUnavailableError("tushare_hk", _DOMAIN, str(exc))

    if is_empty_result(df):
        logger.warning("Tushare HK 实时行情返回空数据")
        raise DataNotFoundError("tushare_hk", _DOMAIN, "无数据")

    logger.info(f"Tushare HK 实时行情: {len(df)} 只")
    return df
