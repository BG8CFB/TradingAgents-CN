"""
Tushare HK 港股财务指标 API — hk_fina_indicator 接口封装。
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

_DOMAIN = "fina_indicator"


async def fetch_fina_indicator(
    api,
    ts_code: str,
) -> Optional[pd.DataFrame]:
    """获取港股财务指标（ROE / EPS / BPS 等）。

    Parameters
    ----------
    api : tushare.pro_api
        已初始化的 Tushare pro_api 实例。
    ts_code : str
        Tushare 格式港股代码，如 "0700.HK"。

    Returns
    -------
    Optional[pd.DataFrame]
        原始 DataFrame，包含 ts_code / end_date / roe / eps / bps 等字段。
    """
    if api is None:
        return None
    try:
        df = await asyncio.to_thread(lambda: api.hk_fina_indicator(ts_code=ts_code))
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "tushare_hk", _DOMAIN)
    except Exception as exc:
        error_code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
        mapped = map_tushare_code(error_code, "tushare_hk", _DOMAIN, str(exc))
        if mapped is not None:
            raise mapped
        raise DataSourceUnavailableError(
            "tushare_hk", _DOMAIN, f"ts_code={ts_code}: {exc}"
        )

    if is_empty_result(df):
        logger.warning(f"Tushare HK 财务指标返回空数据: {ts_code}")
        raise DataNotFoundError("tushare_hk", _DOMAIN, f"{ts_code} 无数据")

    logger.info(f"Tushare HK 财务指标: {ts_code} {len(df)} 条")
    return df
