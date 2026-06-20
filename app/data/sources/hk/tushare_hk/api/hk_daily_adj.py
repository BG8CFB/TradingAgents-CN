"""
Tushare HK 港股每日指标（日线复权数据）API — hk_daily_adj 接口封装。
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

_DOMAIN = "daily_quotes"


def _format_compact(date_str: str) -> str:
    """YYYY-MM-DD -> YYYYMMDD"""
    return str(date_str).replace("-", "") if date_str else ""


async def fetch_daily_adj(
    api,
    ts_code: str,
    start_date: str,
    end_date: str,
) -> Optional[pd.DataFrame]:
    """获取港股日线复权指标数据。

    Tushare HK 的 hk_daily_adj 接口返回 PE / PB / 市值 / 换手率等指标。

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
        原始 DataFrame，包含 ts_code / trade_date / pe / pb / total_mv / circ_mv 等。
    """
    if api is None:
        return None
    start_str = _format_compact(start_date)
    end_str = _format_compact(end_date)
    try:
        df = await asyncio.to_thread(
            lambda: api.hk_daily_adj(
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
        logger.warning(f"Tushare HK 每日指标返回空数据: {ts_code}")
        raise DataNotFoundError("tushare_hk", _DOMAIN, f"{ts_code} 无数据")

    logger.info(f"Tushare HK 每日指标: {ts_code} {len(df)} 条")
    return df
