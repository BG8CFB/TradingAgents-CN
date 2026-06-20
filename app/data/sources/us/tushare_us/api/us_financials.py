"""
Tushare US 美股财务数据 API（利润表/资产负债表/现金流量表）
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

_DOMAIN = "financial_data"


def _to_us_ts_code(symbol: str) -> str:
    """将普通 ticker 转换为 Tushare US ts_code 格式。

    AAPL → AAPL.O (NASDAQ 默认)
    """
    symbol = symbol.upper().strip()
    if "." in symbol:
        return symbol
    return f"{symbol}.O"


async def fetch_financial_data(
    api,
    ts_code: str,
    statement_type: str = "income",
) -> Optional[pd.DataFrame]:
    """获取美股财务报表数据。

    根据 statement_type 调用不同的 Tushare US 财务接口：
    - "income" → api.us_income()（利润表）
    - "balance" → api.us_balancesheet()（资产负债表）
    - "cashflow" → api.us_cashflow()（现金流量表）

    Args:
        api: tushare pro_api 实例
        ts_code: 股票代码，如 "AAPL" 或 "AAPL.O"
        statement_type: 报表类型 ("income"/"balance"/"cashflow")

    Returns:
        财务数据 DataFrame，失败返回 None
    """
    if api is None:
        return None
    us_code = _to_us_ts_code(ts_code)

    api_method_map = {
        "income": "us_income",
        "balance": "us_balancesheet",
        "cashflow": "us_cashflow",
    }
    method_name = api_method_map.get(statement_type, "us_income")

    method = getattr(api, method_name, None)
    if method is None:
        logger.error(f"Tushare US 不支持的方法: {method_name}")
        return None

    try:
        df = await asyncio.to_thread(method, ts_code=us_code)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "tushare_us", _DOMAIN)
    except Exception as exc:
        error_code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
        mapped = map_tushare_code(error_code, "tushare_us", _DOMAIN, str(exc))
        if mapped is not None:
            raise mapped
        raise DataSourceUnavailableError(
            "tushare_us", _DOMAIN, f"ts_code={us_code} ({statement_type}): {exc}"
        )

    if is_empty_result(df):
        logger.warning(f"Tushare US 财务数据返回空数据: {us_code} ({statement_type})")
        raise DataNotFoundError(
            "tushare_us", _DOMAIN, f"{us_code} ({statement_type}) 无数据"
        )

    logger.info(f"Tushare US 财务数据 ({statement_type}): {us_code} {len(df)} 条")
    return df
