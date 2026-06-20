"""
Tushare HK 港股复权因子 API — hk_adjfactor 接口封装。
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

_DOMAIN = "adj_factors"


def _format_compact(date_str: str) -> str:
    """YYYY-MM-DD -> YYYYMMDD"""
    return str(date_str).replace("-", "") if date_str else ""


async def fetch_adj_factors(
    api,
    ts_code: str,
    start_date: str,
    end_date: str,
) -> Optional[pd.DataFrame]:
    """获取港股复权因子。

    Parameters
    ----------
    api : tushare.pro_api
        已初始化的 Tushare pro_api 实例。
    ts_code : str
        Tushare 格式港股代码，如 "0700.HK"。
    start_date : str
        起始日期，格式 YYYY-MM-DD 或 YYYYMMDD。
    end_date : str
        截止日期，格式 YYYY-MM-DD 或 YYYYMMDD。

    Returns
    -------
    Optional[pd.DataFrame]
        原始 DataFrame，包含 ts_code / trade_date / adj_factor 等字段。
    """
    if api is None:
        return None
    start_str = _format_compact(start_date)
    end_str = _format_compact(end_date)
    try:
        df = await asyncio.to_thread(
            lambda: api.hk_adjfactor(
                ts_code=ts_code,
                start_date=start_str,
                end_date=end_str,
            )
        )
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
        logger.warning(f"Tushare HK 复权因子返回空数据: {ts_code}")
        raise DataNotFoundError("tushare_hk", _DOMAIN, f"{ts_code} 无数据")

    logger.info(f"Tushare HK 复权因子: {ts_code} {len(df)} 条")
    return df
