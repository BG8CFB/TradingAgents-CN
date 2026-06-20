"""
Tushare US 美股复权因子 API
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


def _to_us_ts_code(symbol: str) -> str:
    """将普通 ticker 转换为 Tushare US ts_code 格式。

    AAPL → AAPL.O (NASDAQ 默认)
    """
    symbol = symbol.upper().strip()
    if "." in symbol:
        return symbol
    return f"{symbol}.O"


async def fetch_adj_factors(
    api,
    ts_code: str,
    start_date: str,
    end_date: str,
) -> Optional[pd.DataFrame]:
    """获取美股复权因子。

    Args:
        api: tushare pro_api 实例
        ts_code: 股票代码，如 "AAPL" 或 "AAPL.O"
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)

    Returns:
        复权因子 DataFrame，失败返回 None
    """
    if api is None:
        return None
    us_code = _to_us_ts_code(ts_code)
    try:
        df = await asyncio.to_thread(
            api.us_adjfactor,
            ts_code=us_code,
            start_date=start_date.replace("-", ""),
            end_date=end_date.replace("-", ""),
        )
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "tushare_us", _DOMAIN)
    except Exception as exc:
        error_code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
        mapped = map_tushare_code(error_code, "tushare_us", _DOMAIN, str(exc))
        if mapped is not None:
            raise mapped
        raise DataSourceUnavailableError(
            "tushare_us", _DOMAIN, f"ts_code={us_code}: {exc}"
        )

    if is_empty_result(df):
        logger.warning(f"Tushare US 复权因子返回空数据: {us_code}")
        raise DataNotFoundError("tushare_us", _DOMAIN, f"{us_code} 无数据")

    logger.info(f"Tushare US 复权因子: {us_code} {len(df)} 条")
    return df
