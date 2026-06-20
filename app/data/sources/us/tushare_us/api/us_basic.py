"""
Tushare US 美股基础信息 API
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
    """获取美股股票列表（主要美股 + 中概股）。

    Args:
        api: tushare pro_api 实例

    Returns:
        包含美股基础信息的 DataFrame，失败返回 None
    """
    if api is None:
        return None
    try:
        df = await asyncio.to_thread(api.us_basic)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "tushare_us", _DOMAIN)
    except Exception as exc:
        error_code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
        mapped = map_tushare_code(error_code, "tushare_us", _DOMAIN, str(exc))
        if mapped is not None:
            raise mapped
        raise DataSourceUnavailableError("tushare_us", _DOMAIN, str(exc))

    if is_empty_result(df):
        logger.warning("Tushare US 股票列表返回空数据")
        raise DataNotFoundError("tushare_us", _DOMAIN, "无数据")

    logger.info(f"Tushare US 获取股票列表: {len(df)} 只")
    return df
