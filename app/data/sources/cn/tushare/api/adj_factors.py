"""
Tushare 复权因子 API
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

from .connection import TushareConnection

logger = logging.getLogger(__name__)

_DOMAIN = "adj_factors"


async def fetch_adj_factors(
    conn: TushareConnection,
    ts_code: str,
    start_date: str = None,
    end_date: str = None,
) -> Optional[pd.DataFrame]:
    """获取复权因子"""
    if not conn.is_available():
        return None

    params: dict = {"ts_code": ts_code}
    if start_date:
        params["start_date"] = start_date.replace("-", "")
    if end_date:
        params["end_date"] = end_date.replace("-", "")

    try:
        df = await asyncio.to_thread(conn.api.adj_factor, **params)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        # 网络异常：可重试
        raise map_network_exception(exc, "tushare", _DOMAIN)
    except Exception as exc:
        # Tushare 业务异常（限流/token/积分等）：检测返回的 code 属性
        error_code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
        mapped = map_tushare_code(error_code, "tushare", _DOMAIN, str(exc))
        if mapped is not None:
            raise mapped
        # 未知异常：抛 DataSourceUnavailableError 包装，保留原始信息
        raise DataSourceUnavailableError(
            "tushare", _DOMAIN, f"ts_code={ts_code}: {exc}"
        )

    # 空结果（业务正确但无数据）— 用 DataNotFoundError 表示
    if is_empty_result(df):
        logger.warning(f"Tushare 复权因子返回空: ts_code={ts_code}")
        raise DataNotFoundError("tushare", _DOMAIN, f"ts_code={ts_code} 无数据")

    logger.info(f"Tushare 复权因子: {ts_code} {len(df)} 条")
    return df
