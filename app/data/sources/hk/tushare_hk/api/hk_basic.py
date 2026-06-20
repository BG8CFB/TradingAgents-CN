"""
Tushare HK 港股基础信息 API — hk_basic 接口封装。
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

_DOMAIN = "basic_info"


async def fetch_stock_list(api) -> Optional[pd.DataFrame]:
    """获取港股全部股票列表。

    Parameters
    ----------
    api : tushare.pro_api
        已初始化的 Tushare pro_api 实例（使用 TUSHARE_HK_TOKEN）。

    Returns
    -------
    Optional[pd.DataFrame]
        原始 DataFrame，包含 ts_code / name / industry 等字段。
    """
    if api is None:
        return None
    try:
        df = await asyncio.to_thread(lambda: api.hk_basic())
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "tushare_hk", _DOMAIN)
    except Exception as exc:
        error_code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
        mapped = map_tushare_code(error_code, "tushare_hk", _DOMAIN, str(exc))
        if mapped is not None:
            raise mapped
        raise DataSourceUnavailableError("tushare_hk", _DOMAIN, str(exc))

    if is_empty_result(df):
        logger.warning("Tushare HK 股票列表返回空数据")
        raise DataNotFoundError("tushare_hk", _DOMAIN, "无数据")

    logger.info(f"Tushare HK 获取股票列表: {len(df)} 只")
    return df
